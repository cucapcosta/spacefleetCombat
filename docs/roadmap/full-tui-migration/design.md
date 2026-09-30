# Migração completa para a TUI — Design

**Data:** 2026-09-30
**Status:** aprovado (2026-09-30), implementado (2026-09-30)
**Base:** batalha em Textual (commits `aa16090`, `ec42985`) e economia de ação/colisão contínua (`5f6eab2`); regras em `docs/docs/design/turn-structure.md`

## Objetivo

Levar menu principal, campanha, fleet builder e cliente online para o mesmo sistema Textual da batalha, num app único, com o mesmo layout e estilo. Remover o prompt-toolkit.

## Situação atual

| Tela | Sistema | Onde |
|---|---|---|
| Menu principal | prompt-toolkit (`TerminalUI`) | `cli/app.py` |
| Campanha: intervalo, gestão de naves, loja, reparo, fitting, nova campanha | prompt-toolkit | `cli/campaign_cmd.py` |
| Fleet builder | prompt-toolkit | `cli/fleet_builder_cmd.py` |
| Batalha | Textual (`BattleApp`, um `App` próprio) | `tui/battle_app.py` |
| Cliente online | `print` / `input()` | `net/ws_client.py` |

Regras já independentes de UI e reaproveitadas sem mudança: `campaign/rules.py`, `campaign/economy.py`, `campaign/battle.py`, `persistence/*`, `cli/fitting.py` (`fitting_choices`).

## Decisões

| Tema | Decisão |
|---|---|
| Abordagem | Telas nativas Textual; reescreve só a camada de UI |
| App | Um `SpacefleetApp` com telas (`Screen`); batalha vira `BattleScreen` dentro dele |
| Layout | Igual à batalha: cabeçalho de 1 linha, área principal à esquerda, coluna direita (estado + ações), log embaixo, rodapé de teclas |
| Área principal da campanha | Mapa galáctico em braille da rota atual (visual; regras da campanha não mudam) |
| Área principal do hangar e fleet builder | Hangar: arte das naves em blocos sólidos (`▀▄█▓`), lado a lado |
| Arte | Uma por casco (10), guardada no YAML do casco |
| Online | Tela de terminal dentro do app: histórico rolável com o texto ANSI do servidor + campo de comando com histórico. Protocolo não muda |
| prompt-toolkit | Removido (`cli/terminal_ui.py` e dependência) |

## Telas

```
TitleScreen ─┬─ Campaign ─▶ CampaignMenu ─┬─ New ─▶ NewCampaignScreen ─▶ FleetBuilderScreen(campanha) ─▶ CampaignScreen
             │                            └─ Continue ─────────────────────────────────────────────────▶ CampaignScreen
             ├─ Connect ─▶ ConnectScreen ─▶ OnlineScreen
             ├─ Fleet Builder ─▶ FleetBuilderScreen(livre)
             └─ Quit

CampaignScreen ─┬─ B ─▶ BattleScreen ─▶ (fecha batalha, autosave) ─▶ CampaignScreen
                ├─ H ─▶ HangarScreen (refit, flagship, descartar, reparar)
                └─ Y ─▶ HangarScreen em modo estaleiro (comprar casco)
```

### TitleScreen

| Item | Conteúdo |
|---|---|
| Principal | Título "SPACEFLEET COMBAT" + arte de uma nave imperial e uma do Caos |
| Direita | Menu: Campaign, Connect to Server, Fleet Builder, Quit |
| Teclas | ↑/↓ + Enter, letras `C`/`O`/`F`/`Q` |

### CampaignScreen

```
┌ Campaign · Encounter 3/5 · Credits 160 · Foster L2 (XP 280) ────────────────┐
│  ·    ✦ Gothic Sector        ·             │ Fleet                          │
│     ✓ Port Maw ⠈⠒⠤⡀              ·        │ ▸ Vengeful Starstorm [S] ★     │
│  ·            ⠈⠒⠤ ✓ Kharlos        ·      │   Hull ██████████ 12/12        │
│        ·          ⠙⠤⡀                     │   The Indomitable [L]          │
│              ◉ YOU ─── ⚔ Lysades          │   Hull ██████░░░░ 3/4          │
│    ·                     ⠙⠤ ? ·           │ Next: Chaos · 2 ships · 470 pt │
│         ·        ·          ◎ Final       │ [B]attle [H]angar [Y]ard       │
│                                           │ [R]epair all  [W] save         │
├───────────────────────────────────────────┴────────────────────────────────┤
│ Battle victory: 2 enemies destroyed, credits +120. Autosaved.              │
└ b Battle  h Hangar  y Shipyard  r Repair  w Save  ? Help  esc Menu ────────┘
```

| Área | Conteúdo |
|---|---|
| Cabeçalho | Encontro, créditos, comandante (nível, XP) |
| Mapa galáctico | Estrelas de fundo e nomes de sistemas gerados pela `seed` da campanha (determinístico); rota de 6 nós (origem + 5 encontros) ligada por linha braille; `✓` vencido, `◉` posição atual, `⚔` próximo encontro, `◎` final; cor do próximo pela facção inimiga; status `COMPLETED`/`DEFEATED` destacado |
| Direita | Lista da frota (nome, classe, capitânia `★`, barra de casco = `hull_max − hull_damage`), próximo inimigo (`enemy_fleet_for`: facção, naves, pontos), comandante (habilidades, passivas), ações |
| Log | Mensagens que hoje vão para `ui.show` (autosave, resultado de batalha, erros) |
| Batalha | `B` valida (`validate_campaign_state`), `build_battle`, empilha `BattleScreen`; ao dispensar: `ABANDONED` → nada muda, sem salvar; senão `close_battle` + autosave + linha de resultado no log (mesmo texto de hoje) |
| Reparo | `R` repara todos com confirmação e prévia de custo (`repair_all` em candidato) |
| Salvar | `W` autosave explícito |

### HangarScreen

```
┌ Hangar · Credits 160 ───────────────────────────────────────────────────────┐
│                                            │ Vengeful Starstorm ★           │
│          ▄█▄                     ▄         │ Emperor-class Battleship       │
│   ▄▄▄▄███████▄▄▄▄           ▄▄▄███▄▄▶      │ Hull ██████████ 12/12          │
│ ◀██▓▓█████████▓▓██▶▶        ▀▀▀███▀▀       │ Slots                          │
│   ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀                          │ ▸ W1 Port  Mars Battery        │
│  ▸ Vengeful Starstorm      The Indomitable │   W2 Stbd  Mars Battery        │
│                                            │   U1 Improved Augur Array      │
│                                            │ Options: Mk.IV  −40 → 120 cr   │
├────────────────────────────────────────────┴────────────────────────────────┤
│ Refit Port Dorsal → Macro-Cannon Mk.IV (−40 credits). Autosaved.           │
└ ←/→ ship  ↑/↓ slot  enter options  f flagship  x discard  r repair  esc back┘
```

| Área | Conteúdo |
|---|---|
| Principal | Naves da frota lado a lado (arte por casco, tamanho pela classe), nome embaixo; selecionada em destaque, danificada com `▓` extra em vermelho proporcional ao dano |
| Direita | Nave selecionada: casco, dano, batalhas; slots (armas com arco e tamanho, upgrades, doutrina); ao abrir um slot, lista de `fitting_choices` com custo/reembolso e **créditos resultantes** na linha; motivo de indisponível inline |
| Ações | `Enter` aplica fitting (confirmação com prévia), `F` capitânia, `X` descartar (confirmação), `R` reparar esta nave |
| Estaleiro (`Y`) | Principal mostra a arte do casco em foco; direita lista cascos compráveis (custo, nível exigido, motivo indisponível); `Enter` pede nome (Input) e confirma compra |
| Persistência | Toda mudança aplicada em candidato, valida, autosave — como hoje |

### FleetBuilderScreen

| Item | Conteúdo |
|---|---|
| Layout | Igual ao hangar; cabeçalho com facção, nome da frota e **pontos usados / orçamento** |
| Início (modo livre) | Form: facção, orçamento, nome |
| Início (modo campanha) | Facção e orçamento vêm da nova campanha; validador `validate_campaign_fleet` |
| Ações | `A` adicionar nave (lista de cascos com arte ao focar), slots como no hangar, `X` remover, `S` salvar (path), `L` carregar (path), `D` concluir, `Esc` descartar (confirmação) |
| Lógica | Reusa `FleetBuilderSession` ou as funções que ela chama; custo em pontos ao vivo |

### NewCampaignScreen

Form único: facção (seleção), nome do comandante, seed (opcional, inteiro ≥ 0). Substituir save existente pede confirmação. Em seguida `FleetBuilderScreen` em modo campanha; cancelar volta sem tocar no save.

### ConnectScreen e OnlineScreen

| Item | Conteúdo |
|---|---|
| Connect | Form: URL do servidor (padrão atual de `prompt_client_setup`), usuário |
| Online | `RichLog` com o texto do servidor (ANSI → Rich `Text.from_ansi`), `Input` com histórico (↑/↓); cabeçalho com servidor, usuário, estado (conectado, aguardando, sua vez) |
| Rede | Cliente websocket (aiohttp) rodando num worker async do Textual; mesma lógica de mensagens de `SpacefleetWSClient`, extraída para uma classe sem `print`/`input` |
| Saída | `Esc` pede confirmação e desconecta; fim de jogo mostra o resultado e volta ao título |
| Script `spacefleet-ws-client` | Abre o app direto na `OnlineScreen` |

## Arte das naves

| Item | Regra |
|---|---|
| Onde | Campo `art:` (lista de linhas) em cada `data/ships/**/*.yaml` |
| Caracteres | `█▄▀` casco (cor da facção), `▓` detalhe/armadura (tom escuro), `◀▶` motores/proa (cor de brilho), espaço = vazio |
| Orientação | Perfil lateral, proa à direita |
| Tamanho | escolta ~12 col × 3 lin; cruzador leve ~18 × 4; cruzador ~24 × 4; cruzador de batalha ~28 × 5; encouraçado ~34 × 5 |
| Estilo | Imperial: proa em aríete, torre de ponte "catedral"; Caos: silhueta angulosa, espinhos |
| Fallback | Casco sem `art:` usa um bloco genérico pelo tamanho da classe |
| Loader | `HullProfile.art: tuple[str, ...]` carregado do YAML |

## Arquitetura

| Módulo | Responsabilidade |
|---|---|
| `tui/app.py` | `SpacefleetApp`: tema, telas, navegação; entrada de `spacefleet` |
| `tui/screens/title.py` | `TitleScreen` |
| `tui/screens/campaign.py` | `CampaignMenuScreen`, `NewCampaignScreen`, `CampaignScreen` |
| `tui/screens/hangar.py` | `HangarScreen` (refit, estaleiro) |
| `tui/screens/fleet_builder.py` | `FleetBuilderScreen` |
| `tui/screens/online.py` | `ConnectScreen`, `OnlineScreen` |
| `tui/screens/battle.py` | `BattleScreen` (conteúdo atual de `BattleApp`, agora `Screen[BattleOutcome]`) |
| `tui/widgets/galaxy_map.py` | Mapa galáctico (usa `raster`/`camera`) |
| `tui/widgets/hangar_view.py` | Naves lado a lado a partir da arte |
| `tui/widgets/ship_panel.py` | Slots + opções de fitting com prévia de créditos/pontos (compartilhado por hangar e fleet builder) |
| `tui/widgets/confirm.py` | Modais genéricos: confirmar, input de texto |
| `tui/model/galaxy.py` | Geração determinística do mapa a partir da seed (puro) |
| `tui/model/ship_art.py` | Arte → linhas Rich com estilo por caractere e dano (puro) |
| `net/ws_session.py` | Sessão websocket sem I/O de terminal (callbacks de mensagem), usada pela `OnlineScreen` |

### Contratos que mudam

| Item | Antes | Depois |
|---|---|---|
| Batalha | `BattleApp(App)` + `TuiBattleRunner` | `BattleScreen(Screen[BattleOutcome])`; `BattleApp` fica como casca fina que empilha a `BattleScreen` (testes e `run_battle` continuam funcionando) |
| Campanha em teste | `controller_factory` → `BattleRunner` | `CampaignScreen(battle_screen_factory=...)`: testes injetam uma tela falsa que dispensa com o outcome desejado |
| `__main__` | `cli.app.main` | `tui.app.main` |
| `cli/` | UI de menus | Só o que o servidor usa: `display.py`, `colors.py`, `action_parser.py`, `prompts.py` (setup de servidor), `fitting.py` (ou movido para `tui/model/`) |

## Remoções

| Item | Motivo |
|---|---|
| `cli/terminal_ui.py`, `cli/app.py`, `cli/campaign_cmd.py` (UI), `cli/fleet_builder_cmd.py` (UI) | Substituídos pelas telas |
| `prompt-toolkit` em `pyproject.toml` | Sem uso |
| Testes `test_terminal_ui.py`, `test_interactive_*.py`, `terminal_ui_helpers.py`, `test_terminal_smoke.py` | Substituídos por testes Pilot; casos de regra migram |
| `SpacefleetWSClient` com `print`/`input` | Substituído por `ws_session` + `OnlineScreen` |

`net/client.py` (cliente TCP legado, `spacefleet-client`) fica como está: fora de escopo.

## Testes

| Alvo | Tipo | Casos |
|---|---|---|
| `galaxy` | Puro | Mesma seed → mesmo mapa; 6 nós; nomes únicos; nós dentro dos limites |
| `ship_art` | Puro | Todo casco em `data/ships` tem `art`; larguras dentro da faixa da classe; estilo por caractere; dano marca células |
| `ws_session` | Puro/async | Mensagens do servidor viram callbacks; comando vira JSON; desconexão |
| `TitleScreen` | Pilot | Navegação para cada tela e sair |
| `CampaignScreen` | Pilot | Batalha com tela falsa: vitória → `close_battle` + autosave + linha no log; abandono → save intacto; reparo com confirmação; `COMPLETED`/`DEFEATED` bloqueiam batalha |
| `HangarScreen` | Pilot | Refit com prévia de créditos e autosave; indisponível mostra motivo; flagship; descartar; compra no estaleiro |
| `FleetBuilderScreen` | Pilot | Adicionar/configurar/remover com pontos ao vivo; salvar/carregar; modo campanha valida com `validate_campaign_fleet` |
| `NewCampaignScreen` | Pilot | Seed inválida rejeitada; cancelar não toca no save |
| `OnlineScreen` | Pilot | Servidor falso (aiohttp test server ou sessão fake): texto aparece, comando enviado, histórico de input |
| Regras migradas | Existentes | Casos de `test_campaign_cli.py`, `test_fleet_builder_cli.py` que testam regra continuam válidos contra as funções puras |

## Fora de escopo

- Batalha gráfica online (protocolo estruturado).
- Escolha de rota na campanha (mapa ramificado).
- Cliente TCP legado (`net/client.py`).
- Setup interativo do servidor (`prompts.py`) continua em texto.
