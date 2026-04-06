FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY data/ data/
RUN uv sync --frozen --no-dev
ENV PORT=8080
EXPOSE 8080
CMD ["uv", "run", "spacefleet-ws-server"]
