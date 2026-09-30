# Plano — Migração completa para a TUI

Spec: `docs/roadmap/full-tui-migration/design.md`

## Restrições

- Mesmo checkout, sem worktrees; arquivos disjuntos por grupo. Nada é commitado.
- TDD: teste falhando primeiro. Pilot via `asyncio.run(app.run_test())`.
- Gates: `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check <tocados>`, `uv run mypy src`.
- O jogo antigo continua funcionando até W3 (remoções só no fim).

## Ondas

```
W0 (eu) ─▶ W1: A1 ║ A2 ║ A3 ║ A4 ║ A5 ─▶ W2: B1 ║ B2 ║ B3 ║ B4 ─▶ W3: remoções + verificação (eu)
```

| Onda | Grupo | Arquivos principais | Bloqueado por |
|---|---|---|---|
| W0 | Contratos | `tui/screens/__init__.py`, `tui/widgets/confirm.py`, `models/ship_profile.py` (`art`), loader | — |
| W1 | A1 Arte | `data/ships/**/*.yaml` (`art:`), `tui/model/ship_art.py`, `tui/widgets/hangar_view.py` | W0 |
| W1 | A2 Mapa galáctico | `tui/model/galaxy.py`, `tui/widgets/galaxy_map.py` | W0 |
| W1 | A3 BattleScreen | `tui/screens/battle.py`, `tui/battle_app.py` (casca fina) | W0 |
| W1 | A4 Online | `net/ws_session.py`, `tui/screens/online.py`, `net/ws_client.py` (`main`) | W0 |
| W1 | A5 Painel de nave | `tui/widgets/ship_panel.py`, `tui/model/fitting.py` (move de `cli/fitting.py`, com reexport) | W0 |
| W2 | B1 Campanha | `tui/screens/campaign.py` | A2, A3 |
| W2 | B2 Hangar | `tui/screens/hangar.py` | A1, A5 |
| W2 | B3 Fleet builder | `tui/screens/fleet_builder.py` | A1, A5 |
| W2 | B4 App + título | `tui/app.py`, `tui/screens/title.py`, `__main__.py`, `pyproject.toml` scripts | A1 |
| W3 | Remoções + verificação | `cli/*` de UI, testes antigos, `prompt-toolkit` | W2 |

B1 importa `HangarScreen` e `FleetBuilderScreen` por nome de módulo; até B2/B3 existirem usa injeção (`hangar_screen_factory`, `fleet_builder_factory`) para testar com telas falsas. B4 liga tudo no `SpacefleetApp`.

## W0 — Contratos (eu)

1. `models/ship_profile.py`: `HullProfile.art: tuple[str, ...] = ()`; loader do YAML lê `art` (lista de strings). Teste: casco com e sem `art`.
2. `tui/widgets/confirm.py`: `ConfirmScreen(message, yes="Yes", no="No") -> ModalScreen[bool]` e `TextInputScreen(label, default="", validator=None) -> ModalScreen[str | None]` (Esc = None; validator devolve mensagem de erro exibida inline). Testes Pilot.
3. `tui/screens/__init__.py` vazio; convenção: cada tela recebe dependências por construtor (paths, factories), sem globais.

## W1

### A1 — Arte das naves
- Desenhar `art:` para os 10 cascos (6 imperiais, 4 Caos) conforme spec (tamanhos por classe, proa à direita, caracteres `█▄▀▓◀▶`).
- `ship_art.render(hull, faction, damage_ratio=0.0, selected=False) -> list[rich.text.Text]`: estilo por caractere (casco = cor da facção, `▓` tom escuro, `◀▶` brilho), dano pinta fração das células de casco com `▓` vermelho de forma determinística; fallback genérico por classe.
- `HangarView(Widget)`: recebe lista `(hull, name, faction, damage_ratio)`, desenha lado a lado com nome embaixo, quebra em linhas se não couber; `select(index)`; mensagem `ShipPicked(index)` no clique; ←/→ mudam seleção.
- Testes: todos os YAML têm `art`; larguras por classe; render estável; dano marca células; HangarView seleciona e posta mensagem.

### A2 — Mapa galáctico
- `galaxy.generate(seed, encounters=5) -> Galaxy(stars, nodes: [(name, Vector2D)], sector_name)` determinístico (`random.Random(seed)`), nós em rota da esquerda para a direita com variação vertical, nomes de uma lista temática sem repetição.
- `GalaxyMap(Widget)`: canvas braille (reusa `raster`/`camera`), estrelas `·`, linhas da rota, marcadores `✓ ◉ ⚔ ◎`, nomes; `set_state(galaxy, encounter, status, enemy_faction)`.
- Testes: determinismo; 6 nós; nomes únicos; render contém marcadores certos para encontro 3.

### A3 — BattleScreen
- Mover o conteúdo de `BattleApp` para `BattleScreen(Screen[BattleOutcome])` em `tui/screens/battle.py` (bindings, estados, modais); `dismiss(outcome)` no lugar de `exit`.
- `BattleApp` vira casca: `on_mount` empilha `BattleScreen` e sai com o resultado; `run_battle` e `TuiBattleRunner` continuam.
- Testes de batalha existentes passam sem mudar comportamento (ajustar só acesso a widgets via `app.screen`).

### A4 — Online
- `ws_session.WSSession(url, username, on_message: Callable[[dict], None])`: conectar, autenticar, loop de recepção, `send_command(line)` usando o parser atual do cliente; sem `print`/`input`.
- `ConnectScreen` (form URL/usuário, padrões de `prompt_client_setup`) e `OnlineScreen` (RichLog com `Text.from_ansi`, Input com histórico ↑/↓, cabeçalho com estado, `Esc` confirma desconexão).
- `ws_client.main` abre um app mínimo direto na `OnlineScreen` (ou `ConnectScreen` sem argumentos).
- Testes: sessão contra servidor aiohttp de teste (ou fake) — auth, display, command; OnlineScreen mostra texto e envia comando.

### A5 — Painel de nave
- Mover `cli/fitting.py` para `tui/model/fitting.py` (deixar `cli/fitting.py` reexportando até W3).
- `ShipPanel(Widget)`: mostra casco/dano/batalhas; lista de slots (armas com arco/tamanho, upgrades, doutrina); `Enter` abre opções (`fitting_choices`) com linha de custo e **saldo resultante** calculado por um `preview: Callable[[slot, choice], tuple[int, str | None]]` injetado (créditos na campanha, pontos no fleet builder; str = motivo indisponível); posta `FittingChosen(slot, choice)`; `Esc` volta aos slots.
- Testes: slots listados; prévia usa o callable; indisponível mostra motivo e não posta.

## W2

### B1 — Campanha
- `CampaignMenuScreen` (New/Continue/Back), `NewCampaignScreen` (form + validação de seed + confirmação de substituir save + chama `fleet_builder_factory` em modo campanha), `CampaignScreen` (layout do spec; batalha via `battle_screen_factory`, `close_battle`, autosave, log; reparo com confirmação; salvar; bloqueios por status).
- Migrar casos de regra de `tests/test_campaign_cli.py` / `test_interactive_campaign.py` para Pilot em `tests/test_tui_campaign.py`.

### B2 — Hangar
- `HangarScreen(campaign, path, on_change)`: `HangarView` + `ShipPanel` com prévia em créditos (`reequip_ship` em candidato); flagship, descartar, reparar nave; modo estaleiro (`buy_ship`, cascos compráveis com motivo, nome via `TextInputScreen`).
- Testes em `tests/test_tui_hangar.py`.

### B3 — Fleet builder
- `FleetBuilderScreen(faction=None, budget=None, name=None, validator=None, mode="free"|"campaign")` → `dismiss(FleetSpec | None)`; form inicial no modo livre; adicionar/configurar/remover com pontos ao vivo; salvar/carregar via `persistence/fleet_save`.
- Migrar casos de `tests/test_fleet_builder_cli.py` / `test_interactive_fleet_builder.py` para `tests/test_tui_fleet_builder.py`.

### B4 — App e título
- `SpacefleetApp` (tema, CSS comum, telas), `TitleScreen` com arte e menu, `main()`; `__main__` usa `tui.app.main`; scripts do `pyproject.toml` apontados.
- Testes: navegação do título para cada tela (com factories falsas) e sair.

## W3 — Remoções e verificação (eu)

1. Remover `cli/terminal_ui.py`, `cli/app.py`, UI de `cli/campaign_cmd.py` e `cli/fleet_builder_cmd.py` (mover para `campaign/` ou `tui/model/` qualquer função de regra ainda usada), `cli/fitting.py` reexport, testes antigos listados no spec, `prompt-toolkit` do `pyproject.toml` + `uv lock`.
2. `grep -rn "prompt_toolkit\|TerminalUI\|terminal_ui" src tests` vazio.
3. Gates completos.
4. Jogo real em tmux: título → nova campanha (seed) → fleet builder → campanha (mapa) → hangar refit → estaleiro → batalha → volta com resultado e autosave; fleet builder livre salvar/carregar; online contra `make ws-server` local. Save de verdade do usuário preservado (backup/restore).
