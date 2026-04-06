.PHONY: help install play server ws-server ws-client client test lint typecheck check build build-client clean

.DEFAULT_GOAL := help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install all dependencies (including dev)
	uv sync --extra dev

play:  ## Launch the interactive game menu
	uv run spacefleet

server:  ## Start game server (PORT=9876 MODE=pve PLAYERS=2 SHIPS=3)
	uv run spacefleet-server \
		--port $(or $(PORT),9876) \
		--mode $(or $(MODE),pve) \
		--players $(or $(PLAYERS),2) \
		--ships-per-player $(or $(SHIPS),3)

ws-server:  ## Start WebSocket server (PORT=8080 GAME_MODE=pve EXPECTED_PLAYERS=1 SHIPS_PER_PLAYER=3)
	PORT=$(or $(PORT),8080) \
	GAME_MODE=$(or $(GAME_MODE),pve) \
	EXPECTED_PLAYERS=$(or $(EXPECTED_PLAYERS),1) \
	SHIPS_PER_PLAYER=$(or $(SHIPS_PER_PLAYER),3) \
	uv run spacefleet-ws-server

ws-client:  ## Connect via WebSocket (URL=wss://game.forjadeguerra.com.br/ws USER=player1)
	uv run spacefleet-ws-client \
		$(or $(URL),wss://game.forjadeguerra.com.br/ws) \
		--user $(or $(USER),player1)

client:  ## Connect to TCP server (HOST=localhost PORT=9876 USER=player1)
	uv run spacefleet-client \
		$(or $(HOST),localhost) \
		--port $(or $(PORT),9876) \
		--user $(or $(USER),player1)

test:  ## Run tests with pytest
	uv run pytest

lint:  ## Lint with ruff (check + format check)
	uv run ruff check src tests
	uv run ruff format --check src tests

lint-fix:  ## Auto-fix lint and formatting issues
	uv run ruff check --fix src tests
	uv run ruff format src tests

typecheck:  ## Run mypy type checking
	uv run mypy src

check: lint typecheck test  ## Run all quality checks

build:  ## Build wheel and sdist
	uv build

build-client:  ## Build standalone executable (dist/spacefleet-client)
	uv run pyinstaller \
		--onefile \
		--name spacefleet-client \
		--strip \
		--clean \
		src/spacefleet/net/ws_client.py

clean:  ## Remove build artifacts and caches
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
