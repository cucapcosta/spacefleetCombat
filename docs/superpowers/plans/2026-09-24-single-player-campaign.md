# Single-Player Campaign Implementation Plan

**Status:** Approved by the user; implementation in progress.

> **For agentic workers:** After user approval, follow this plan task by task with bounded Sol implementation workers, Terra review gates, and Astra making architectural or consequential ambiguity decisions. Workers must not spawn subagents. Stop and report to Astra if a task requires a new architecture, broader combat rewrite, security/concurrency decision, or substantially more code than described here.

**Goal:** Deliver a five-battle local campaign in which the player builds and manually commands a persistent fleet, earns and spends credits, carries damage/XP/casualties forward, and can save and continue from the last interval.

**Architecture:** Add a small campaign layer around the existing `FleetSpec`, `Commander`, `GameState`, `add_custom_fleet`, `AIController`, and `resolve_turn` APIs. Campaign records own stable roster IDs and interval state; each battle materializes a fresh runtime `GameState` and retains one explicit stable-ID/runtime-ID map until closure. A synchronous CLI controller gathers and reviews player orders, then delegates all combat rules to the existing resolver.

**Tech Stack:** Python 3.12+, dataclasses/enums, JSON and atomic `os.replace`, existing registries and combat engine, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-24-single-player-campaign-design.md`

## Global Constraints

- The implementation target is exactly five manual battles; simultaneous elimination, surrender, and 60 turns without victory are defeats.
- Reuse `spacefleet.net.game_state.GameState`, `add_custom_fleet`, `validate_command`, `AIController`, `ServerRenderer`, `parse_ability_command`, and `resolve_turn`; never use or copy `DemoBattle` resolution.
- The player controls only the player fleet. Call `AIController.generate_commands(state, controlled_ids=session.enemy_runtime_ids)` only after the player confirms the turn.
- Keep the existing global catalogs unchanged. Campaign eligibility permits only `BATTERY` and `LANCE`; rejects upgrades `power_ram`, `automated_reload`; abilities `augur_probe`, `torpedo_barrage`; passives `short_burn_torpedoes`, `reload_drills`; and every trait.
- Apply campaign eligibility at creation, enemy preset construction, store mutations, battle assembly, and save load. Use full `FleetSpec` validation for battle-ready fleets; interval/save validation checks each surviving ship and permits an empty roster or missing flagship as specified in Task 1.
- `improved_augur_array` remains eligible. Show unsupported catalog entries with a reason instead of silently hiding them.
- The initial build budget is 800 credits. Persist the unused amount as `CampaignState.credits`; never use `FleetBuilderSession.remaining` as the campaign balance after creation.
- Persistent ship identity is `CampaignShip.id`, never name or list position. IDs are unique, monotonically allocated, and never reused.
- Restore the persisted commander and ship hull damage/veterancy before the first `PassiveBus.build(state)`. Reset all other battle-only state through fresh materialization.
- The resolver already grants victory XP and crew veterancy. Campaign closure copies those values and never grants them again.
- Reward: victory only, `100 + 20 * initial_enemy_count_minus_survivors + 15 * surviving_player_count`; defeat gives zero.
- Store mutations are atomic. Replacement refund is 50% of each removed item's catalog cost, rounded down per item. Repair costs 8 credits per missing hull point.
- Re-equipping preserves absolute damage and veterancy and must reject a new maximum hull `M` when `M - damage <= 0`.
- Save only campaign records as a separate, versioned JSON format. Write a temporary file in the target directory and replace the destination only after a successful complete write.
- Mid-battle saving is out of scope. Quitting a battle explains that Continue returns to the prior interval and must not close or advance the encounter.
- No strategic map, territorial economy, narrative, multiplayer work, torpedoes, Nova Cannon, `power_ram`, augur/torpedo stubs, full commander loadout progression, subsystem-damage persistence, or changes to the historical 2026-08-04 gauntlet files.
- Preserve repository conventions and public APIs. No new dependency, transaction framework, event framework, generic repository layer, or broad refactor.
- Each implementation task gets a focused Sol worker. After the task passes its targeted tests, use a Terra reviewer for that task's diff; Astra resolves findings before the next dependent task.
- Implementation starts only after the user reviews and approves this plan.

## Implementation setup and recorded baseline

The pre-plan baseline is `uv run --no-sync pytest -q`: **344 passed in 3.71s**. Ruff and mypy were unavailable because the development executables are not installed in the current environment; this is an environment failure, not a code failure. After plan approval and before Task 1 changes, run `uv sync --extra dev`, inspect `git diff -- uv.lock`, and preserve `uv.lock` if dependency resolution made no intended project dependency change. Then record `uv run --no-sync ruff check src tests`, `uv run --no-sync ruff format --check src tests`, `uv run --no-sync mypy src`, and `uv run --no-sync pytest -q` as the implementation baseline.

## Shared campaign test fixtures

Task 1 creates `tests/campaign_helpers.py`; later campaign tests import these three helpers instead of inventing scenario factories:

```python
def supported_fleet(faction: Faction = Faction.IMPERIAL_NAVY) -> FleetSpec:
    if faction is Faction.IMPERIAL_NAVY:
        ships = [
            ShipSpec("Test Flag", "dauntless_light_cruiser", {1: "macro_cannon_2", 2: "macro_cannon_2", 3: "lance_2"}),
            ShipSpec("Test Escort", "sword_frigate", {1: "macro_cannon_1", 2: "macro_cannon_1"}),
        ]
    else:
        ships = [
            ShipSpec("Test Flag", "slaughter_cruiser", {1: "macro_cannon_3", 2: "macro_cannon_3", 3: "lance_2"}),
            ShipSpec("Test Escort", "iconoclast_destroyer", {1: "macro_cannon_1", 2: "macro_cannon_1"}),
        ]
    return FleetSpec(name="Test Fleet", faction=faction, ships=ships, flagship_index=0)

def campaign_state(faction: Faction = Faction.IMPERIAL_NAVY) -> CampaignState:
    return new_campaign(supported_fleet(faction), "Test Commander", seed=7)

class ScriptedIO:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)
        self.outputs: list[str] = []

    def input(self, _prompt: str) -> str:
        return next(self._lines)

    def output(self, text: str) -> None:
        self.outputs.append(text)
```

Tests create special conditions by mutating a local `campaign_state()` or `build_battle(campaign)` result explicitly. Do not add one-off scenario factories.

## Review Focus

1. **Unsupported or malformed loaded content:** load must reject it with a readable error while the caller retains the current in-memory session; pinned in Task 7 save tests.
2. **Failure halfway through a purchase, repair-all, re-equip, or save:** roster, flagship, credits, next ID, and previous file remain byte-for-byte/logically unchanged; pinned in Tasks 5 and 7.
3. **Roster edits around casualties and flagship loss:** stable identity must survive loss, discard, purchase, reorder, re-equip, and battle/runtime ID changes; pinned in Tasks 2, 5, and 6.
4. **Repeated or ambiguous battle ending:** simultaneous elimination, turn limit, surrender, and a second closure call must never award or advance twice; pinned in Task 6.
5. **Cancellation at destructive or long-running CLI points:** cancelling save replacement, discard, new campaign, or a battle leaves the prior save/interval usable; pinned in Tasks 3 and 8.

---

### Task 1: Campaign records, eligibility, presets, and builder return seam

**Files:**
- Create: `src/spacefleet/campaign/models.py`
- Create: `src/spacefleet/campaign/rules.py`
- Create: `tests/campaign_helpers.py`
- Modify: `src/spacefleet/net/game_state.py:234-286`
- Modify: `src/spacefleet/cli/fleet_builder_cmd.py:336-end`
- Test: `tests/test_campaign_rules.py`
- Test: `tests/test_fleet_builder_cli.py`

**Interfaces:**
- Consumes: `FleetSpec`, `ShipSpec`, `fleet_points`, `validate_fleet_spec`; registry `get_or_none`/`all`; existing `_build_starter_commander` behavior.
- Produces:
  - `CampaignStatus(StrEnum)` with `ACTIVE`, `COMPLETED`, `DEFEATED`.
  - `BattleOutcome(StrEnum)` with `VICTORY`, `DEFEAT`, `SURRENDER`, `TURN_LIMIT`, `ABANDONED`.
  - `CampaignShip(id: str, spec: ShipSpec, hull_damage: int = 0, battles_survived: int = 0)`.
  - `CampaignState(fleet_name: str, seed: int, encounter: int, status: CampaignStatus, credits: int, next_ship_id: int, faction: Faction, roster: list[CampaignShip], flagship_id: str | None, commander: Commander, last_resolved_battle_id: str | None = None)`.
  - `validate_campaign_fleet(fleet: FleetSpec, commander: Commander | None = None) -> None`.
  - `validate_campaign_state(campaign: CampaignState, *, require_battle_ready: bool = False) -> None`.
  - `campaign_fleet_spec(campaign: CampaignState) -> FleetSpec`.
  - `new_campaign(fleet: FleetSpec, commander_name: str, seed: int | None) -> CampaignState`.
  - `enemy_fleet_for(player_faction: Faction, encounter: int) -> FleetSpec`.
  - Public `build_starter_commander(fleet_id: str, faction: Faction) -> Commander`; retain `_build_starter_commander` as a compatibility alias if tests/imports require it.
  - `run_fleet_builder(*, faction: Faction | None = None, budget: int | None = None, name: str | None = None) -> FleetSpec | None`; existing no-argument menu behavior remains valid.

- [x] **Step 1: Write failing campaign-rule tests**

```python
def test_new_campaign_converts_builder_remainder_to_real_credits() -> None:
    fleet = supported_fleet()
    campaign = new_campaign(fleet, "Admiral Voss", seed=41)
    assert campaign.fleet_name == fleet.name
    assert campaign.credits == 800 - fleet_points(fleet)
    assert [s.id for s in campaign.roster] == ["ship-1", "ship-2"]
    assert campaign.next_ship_id == 3

@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda f: f.ships[0].weapons.__setitem__(3, "standard_torpedoes"), "torpedo"),
        (lambda f: f.ships[0].upgrade_ids.append("power_ram"), "power_ram"),
    ],
)
def test_campaign_eligibility_rejects_implemented_later_content(mutate, message) -> None:
    fleet = supported_fleet()
    mutate(fleet)
    with pytest.raises(FleetSpecError, match=message):
        validate_campaign_fleet(fleet)

def test_enemy_presets_are_legal_supported_and_strictly_increase_in_cost() -> None:
    for player_faction in Faction:
        fleets = [enemy_fleet_for(player_faction, i) for i in range(1, 6)]
        for fleet in fleets:
            validate_fleet_spec(fleet)
            validate_campaign_fleet(fleet)
        assert [fleet_points(f) for f in fleets] == sorted(
            {fleet_points(f) for f in fleets}
        )
```

Also pin unknown encounter `0/6`, foreign-faction catalog IDs, blocked abilities/passives, non-empty traits, `improved_augur_array`, and builder cancellation returning `None`. Pin the state boundary separately: an interval may have an empty roster or `flagship_id=None`, while `validate_campaign_state(campaign, require_battle_ready=True)` rejects either before battle.

- [x] **Step 2: Run the focused tests and confirm the expected failures**

Run: `pytest tests/test_campaign_rules.py tests/test_fleet_builder_cli.py -q`

Expected: new campaign imports fail; the existing builder tests still pass.

- [x] **Step 3: Implement the records and one eligibility boundary**

Keep blocked IDs as immutable constants in `campaign/rules.py`. Validate catalog existence and normal faction/slot/flagship rules first, then campaign restrictions. Allocate initial IDs once in fleet order; thereafter callers use `next_ship_id` only.

```python
SUPPORTED_WEAPON_TYPES = frozenset({WeaponType.BATTERY, WeaponType.LANCE})
INITIAL_CREDITS = 800
BLOCKED_UPGRADES = frozenset({"power_ram", "automated_reload"})
BLOCKED_ABILITIES = frozenset({"augur_probe", "torpedo_barrage"})
BLOCKED_PASSIVES = frozenset({"short_burn_torpedoes", "reload_drills"})

def new_campaign(fleet: FleetSpec, commander_name: str, seed: int | None) -> CampaignState:
    validate_fleet_spec(fleet, budget=INITIAL_CREDITS)
    commander = build_starter_commander("player", fleet.faction)
    commander.name = commander_name
    validate_campaign_fleet(fleet, commander)
    roster = [
        CampaignShip(id=f"ship-{index}", spec=deepcopy(spec))
        for index, spec in enumerate(fleet.ships, start=1)
    ]
    return CampaignState(
        seed=seed if seed is not None else secrets.randbits(63),
        fleet_name=fleet.name,
        encounter=1,
        status=CampaignStatus.ACTIVE,
        credits=INITIAL_CREDITS - fleet_points(fleet),
        next_ship_id=len(roster) + 1,
        faction=fleet.faction,
        roster=roster,
        flagship_id=roster[fleet.flagship_index].id,
        commander=commander,
    )
```

`validate_campaign_state` is the single aggregate invariant boundary. It always checks campaign scalar limits, commander/faction/catalog eligibility, unique stable IDs, unique ship names, each individual ship spec, non-negative damage/veterancy, ID counter monotonicity, and that a non-`None` flagship references the roster. It intentionally permits an empty roster and missing flagship for a post-loss or edited interval. With `require_battle_ready=True`, additionally construct `campaign_fleet_spec`, require non-empty roster and flagship, and call normal full-fleet validation.

Use fixed in-code `FleetSpec` factories, not a new data schema. Start from default loadouts and explicitly omit unsupported torpedo/Nova slots for both factions. Validate the resulting presets. Use these increasing compositions as the balance starting point:

| Enemy faction | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Chaos | 2 Iconoclast | Slaughter + 2 Iconoclast | Murder + Slaughter | Desolator + 2 Iconoclast | Desolator + Murder + Slaughter |
| Imperial | 2 Sword | Dauntless + 2 Sword | Lunar + Dauntless | Emperor + 2 Sword | Emperor + Lunar + Dauntless |

Tests, rather than comments, are the guard that presets remain legal and strictly increase in total points when catalog costs change.

Planning verification against the current catalogs, after excluding unsupported
weapons: Chaos costs are `80, 310, 470, 630, 1020`; Imperial costs are
`90, 255, 410, 700, 1020`. Both sequences pass normal fleet validation and
strictly increase. These checks establish legality, not gameplay balance.

- [x] **Step 4: Add the narrow builder return seam**

Parameter values supplied by campaign creation skip only their corresponding prompts. `done` returns a deep-copied, validated `FleetSpec`; EOF, `KeyboardInterrupt`, or an explicit top-level `cancel` returns `None`. Keep the existing standalone builder menu working when callers ignore the return value.

- [x] **Step 5: Run focused tests**

Run: `pytest tests/test_campaign_rules.py tests/test_fleet_builder_cli.py tests/test_custom_fleet_assembly.py -q`

Expected: PASS.

- [x] **Step 6: Commit the independently reviewable milestone**

```bash
git add src/spacefleet/campaign/models.py src/spacefleet/campaign/rules.py tests/campaign_helpers.py \
  src/spacefleet/net/game_state.py src/spacefleet/cli/fleet_builder_cmd.py \
  tests/test_campaign_rules.py tests/test_fleet_builder_cli.py
git commit -m "feat: add campaign roster and eligibility rules"
```

**Acceptance:** A valid 800-credit fleet becomes a stable-ID campaign preserving its fleet name and real leftover credits; every preset validates through both normal and campaign rules; catalog restrictions cannot be bypassed through direct API calls.

**Escalate to Astra if:** normal fleet validation makes any listed preset impossible without changing fleet composition rules or catalogs.

---

### Task 2: Materialize persistent rosters into fresh battles

**Files:**
- Create: `src/spacefleet/campaign/battle.py`
- Modify: `src/spacefleet/campaign/__init__.py`
- Test: `tests/test_campaign_battle.py`

**Interfaces:**
- Consumes: Task 1 models/rules; `GameState`, `add_custom_fleet`, `DiceRoller`, `AbilityState`, `PassiveBus`, `SkillRegistry`, and `apply_flagship_upgrade_charges`.
- Produces:
  - `BattleSession(battle_id: str, encounter: int, state: GameState, player_id: str, player_runtime_by_campaign: dict[str, str], enemy_runtime_ids: list[str], initial_enemy_count: int)`.
  - `build_battle(campaign: CampaignState) -> BattleSession`.
  - Internal `_runtime_commander_copy(saved: Commander) -> Commander`, which copies persistent identity/progression/loadout and initializes fresh charges with no cooldowns, preparations, or buffs.

- [x] **Step 1: Write failing assembly tests**

```python
def test_build_battle_restores_identity_damage_crew_and_commander_before_passives() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.roster[0].battles_survived = 3
    campaign.commander.xp = 275
    session = build_battle(campaign)
    runtime_id = session.player_runtime_by_campaign[campaign.roster[0].id]
    ship = session.state.ships[runtime_id]
    assert ship.hull_current == ship.hull_max - 2
    assert ship.battles_survived == 3
    assert session.state.fleets["player"].commander is not campaign.commander
    assert session.state.fleets["player"].commander.xp == 275
    assert session.state.passives is not None

def test_mapping_survives_roster_reorder() -> None:
    campaign = campaign_state()
    campaign.roster.reverse()
    session = build_battle(campaign)
    assert set(session.player_runtime_by_campaign) == {s.id for s in campaign.roster}
    assert len(set(session.player_runtime_by_campaign.values())) == len(campaign.roster)
```

Also test deterministic battle IDs/seeds, encounter-specific preset, runtime flagship mapping, fresh shields/morale/fires/subsystems/stance/cooldowns, and rejection before mutating a `GameState` when damage or eligibility is invalid. Assert `build_battle` calls `validate_campaign_state(campaign, require_battle_ready=True)`, so empty-roster and missing-flagship intervals are loadable but cannot start combat.

- [x] **Step 2: Run and confirm red**

Run: `pytest tests/test_campaign_battle.py -q`

Expected: FAIL because `campaign.battle` does not exist.

- [x] **Step 3: Implement assembly with one-time zipping**

```python
player_ids = add_custom_fleet(state, "player", campaign_fleet_spec(campaign), start_x=-50)
mapping = dict(zip((s.id for s in campaign.roster), player_ids, strict=True))
enemy_spec = enemy_fleet_for(campaign.faction, campaign.encounter)
enemy_ids = add_custom_fleet(state, "enemy", enemy_spec, start_x=50, heading=180)
state.ai_ships = list(enemy_ids)

for saved in campaign.roster:
    runtime = state.ships[mapping[saved.id]]
    runtime.hull_current = runtime.hull_max - saved.hull_damage
    runtime.battles_survived = saved.battles_survived

# Replace add_custom_fleet's starter, initialize fresh charges/cooldowns, map flagship,
# apply flagship upgrade charges, and only then build PassiveBus.
state.fleets["player"].commander = _runtime_commander_copy(campaign.commander)
state.fleets["player"].flagship_ship_id = mapping[campaign.flagship_id]
state.passives = PassiveBus.build(state)
```

Use `battle_id = f"{campaign.seed}:{campaign.encounter}"` and battle seed `campaign.seed + campaign.encounter`. Never reconstruct stable identity from runtime IDs, names, or list positions after this point.

- [x] **Step 4: Run focused assembly tests**

Run: `pytest tests/test_campaign_battle.py tests/test_custom_fleet_assembly.py tests/test_passive_bus_dispatch.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/spacefleet/campaign/battle.py src/spacefleet/campaign/__init__.py \
  tests/test_campaign_battle.py
git commit -m "feat: materialize campaign fleets into battles"
```

**Acceptance:** A campaign battle uses a fresh resolver state, exact stable/runtime mapping, persisted commander/damage/veterancy, fresh transient systems, supported reproducible enemies, and correctly built passives.

**Escalate to Astra if:** restoring the commander before passives requires changing `PassiveBus` lifecycle or making `add_custom_fleet` campaign-aware.

---

### Task 3: Playable synchronous local battle controller

**Files:**
- Create: `src/spacefleet/cli/action_parser.py`
- Create: `src/spacefleet/cli/local_battle.py`
- Create: `src/spacefleet/cli/campaign_cmd.py`
- Modify: `src/spacefleet/net/client.py:205-288`
- Modify: `src/spacefleet/phases/command_phase.py:41-180`
- Modify: `src/spacefleet/cli/app.py:21-40,193-end`
- Test: `tests/test_local_battle_controller.py`
- Test: `tests/test_command_phase_validation.py`

**Interfaces:**
- Consumes: Task 1 `BattleOutcome`; Task 2 `BattleSession`; `ServerRenderer`; `validate_command(msg, ship, player_id, owner_lookup) -> Command | str`; `parse_ability_command(tokens, fleet_id)`; `AIController.generate_commands(state, controlled_ids=session.enemy_runtime_ids)`; `resolve_turn(state, commands, ability_orders)`.
- Produces:
  - `parse_action_command(ship_id: str, tokens: list[str]) -> dict[str, object] | str` shared by network client and local controller.
  - Pure `validate_ability_order(state: CoreGameState, fleet: Fleet, commander: Commander, order: AbilityOrder, *, cooldown_will_tick: bool = False) -> str | None` used by `_dispatch` and local preflight.
  - `LocalBattleController(session: BattleSession, *, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print, renderer: ServerRenderer | None = None, ai: AIController | None = None, turn_limit: int = 60)` and `.run() -> BattleOutcome`.
  - Initial `run_new_campaign(save_path: Path | None = None) -> None` seam in `campaign_cmd.py`; Task 8 expands it into the full loop.

- [ ] **Step 1: Write controller tests with scripted input**

```python
def test_invalid_and_query_input_do_not_advance_then_ability_reaches_resolver(monkeypatch) -> None:
    session = build_battle(campaign_state())
    seen: list[dict[str, AbilityOrder]] = []
    enemy_id = session.enemy_runtime_ids[0]
    flagship = session.state.fleets["player"].flagship_in(session.state)
    assert flagship is not None
    session.state.ships[enemy_id].position = flagship.position

    def resolve_once(state, commands, ability_orders):
        seen.append(ability_orders)
        for ship_id in session.enemy_runtime_ids:
            state.ships[ship_id].take_hull_damage(state.ships[ship_id].hull_max)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    io = ScriptedIO([
        "status", "fire nope", "pass", "pass",
        f"ability concentrated_fire {enemy_id}", "review", "confirm",
    ])
    outcome = LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()
    assert session.state.turn == 1
    assert seen[0]["player"].ability_id == "concentrated_fire"
    assert "Invalid" in "\n".join(io.outputs)

def test_ai_receives_only_explicit_enemy_ids_after_turn_increment() -> None:
    session = build_battle(campaign_state())
    calls: list[tuple[list[str], int]] = []
    ai = Mock()
    ai.generate_commands.side_effect = lambda state, controlled_ids: (
        calls.append((list(controlled_ids), state.turn)) or {}
    )
    io = ScriptedIO(["pass", "pass", "review", "confirm", "quit"])
    LocalBattleController(session, input_fn=io.input, output_fn=io.output, ai=ai).run()
    assert calls == [(session.enemy_runtime_ids, 1)]

def test_quit_mid_battle_abandons_without_mutating_campaign_interval() -> None:
    campaign = campaign_state()
    before = deepcopy(campaign)
    io = ScriptedIO(["quit"])
    outcome = LocalBattleController(
        build_battle(campaign), input_fn=io.input, output_fn=io.output
    ).run()
    assert outcome is BattleOutcome.ABANDONED
    assert campaign == before
```

Also test same seed + same orders produce equivalent turn logs/state; queued stance changes apply only on `confirm`; `revise` discards queued orders/stances; surrender; renderer output; cooldown `1` accepted during preflight because command phase ticks before dispatch; and an ability that becomes invalid during resolution emits/renderers an `AbilityRejectedEvent` rather than rewinding the turn.

- [ ] **Step 2: Run and confirm red**

Run: `pytest tests/test_local_battle_controller.py tests/test_command_phase_validation.py -q`

Expected: FAIL on missing parser/controller and public ability validation.

- [ ] **Step 3: Extract only the shared action parser and pure ability preflight**

Move the network client's existing CLI token conversion into `cli/action_parser.py` without changing accepted syntax. Keep authoritative validation in `validate_command`.

Extract the checks currently embedded in `_dispatch` into `validate_ability_order`. The pure function must not create `AbilityState`, consume charges, mutate cooldown, or deep-copy state. For local preflight only, treat `cooldown_remaining == 1` as available because the resolver ticks it before dispatch; `_dispatch` calls the same validator after the real tick with `cooldown_will_tick=False`.

- [ ] **Step 4: Implement the collect-review-confirm loop**

For each alive player ship, accept free `status`, `scan`, `weapons`, `help`, and `stance` queries without advancing. Convert costed commands with the shared parser, then pass the raw mapping to `validate_command`. Collect at most one ability order; `ability skip` explicitly submits none. Queue stance choices as values, not mutations. Display the full pending turn and accept `confirm`, `revise`, `surrender`, or `quit`.

On confirm only:

```python
for ship_id, stance in pending_stances.items():
    state.ships[ship_id].switch_stance(stance)
state.advance_turn()
ai_commands = self.ai.generate_commands(state, controlled_ids=session.enemy_runtime_ids)
log = resolve_turn(state, player_commands | ai_commands, ability_orders)
```

Check victory/defeat after resolution, with simultaneous elimination resolving as `DEFEAT`. Stop at 60 completed turns with `TURN_LIMIT`. `quit` returns `ABANDONED` and prints that Continue returns to the previous interval.

- [ ] **Step 5: Add the first playable menu milestone**

Add one local campaign menu entry that prompts faction/name/optional integer seed, calls the builder with budget 800, creates the in-memory campaign, builds encounter 1, and runs `LocalBattleController`. At this milestone it may report the result and return to the main menu; do not add temporary combat rules or a second loop. Task 8 extends the same `campaign_cmd.py` entry into store/save/continuation.

- [ ] **Step 6: Run targeted tests and one scripted smoke command**

Run: `pytest tests/test_local_battle_controller.py tests/test_command_phase_validation.py tests/test_cli_ability_command.py tests/test_ai_fleet_pilot.py -q`

Expected: PASS. Then run: `python -m spacefleet` and manually reach the local battle prompt, issue `status`, one valid ship order, one supported ability, review, confirm, and quit.

- [ ] **Step 7: Commit**

```bash
git add src/spacefleet/cli/action_parser.py src/spacefleet/cli/local_battle.py \
  src/spacefleet/cli/campaign_cmd.py src/spacefleet/net/client.py \
  src/spacefleet/phases/command_phase.py src/spacefleet/cli/app.py \
  tests/test_local_battle_controller.py tests/test_command_phase_validation.py
git commit -m "feat: add playable local fleet battles"
```

**Acceptance:** From the main menu, a custom supported fleet can fight preset AI without a server; queries/invalid input/review do not advance; movement, firing, boarding, stance, and supported ability orders reach the existing resolver.

**Escalate to Astra if:** the controller needs to duplicate resolution or mutate state to preview commands.

---

### Task 4: Credit supported ability kills exactly once

**Files:**
- Modify: `src/spacefleet/commander/abilities.py:170-180,302-322`
- Modify: `src/spacefleet/combat/resolution.py:55-90`
- Modify: `src/spacefleet/combat/projectile_resolution.py:80-105,240-270`
- Modify: `src/spacefleet/net/game_state.py:30-45`
- Modify: `src/spacefleet/net/turn_resolver.py:185-220,260-280,430-450,596-end`
- Test: `tests/test_campaign_kill_credit.py`
- Test: `tests/test_effect_steps.py`

**Interfaces:**
- Consumes: `AreaHullDamageHitEvent`, `DestroyedEvent`, `GameState.owner_of`, and existing weapon/projectile kill paths.
- Produces: identity-based `_credit_destroyed_ship(state, target_ship_id: str, *, killer_ship_id: str | None = None, killer_fleet_id: str | None = None, emit: Callable[[TurnEvent], None]) -> None`; `GameState.credited_destroyed_ship_ids: set[str]`.

- [x] **Step 1: Write focused kill-credit failures**

```python
def test_warp_rift_enemy_kill_credits_casting_commander_fleet() -> None:
    session = build_battle(campaign_state(Faction.CHAOS_FLEET))
    state = session.state
    commander = state.fleets["player"].commander
    assert commander is not None
    commander.active_ability_ids.append("warp_rift")
    commander.ability_state["warp_rift"] = AbilityState(remaining_charges=1)
    flagship = state.fleets["player"].flagship_in(state)
    assert flagship is not None
    enemy_id = session.enemy_runtime_ids[0]
    enemy = state.ships[enemy_id]
    enemy.position = flagship.position
    enemy.shields_current = 0
    enemy.hull_current = 1
    for other_id in session.enemy_runtime_ids[1:]:
        state.ships[other_id].position = Vector2D(500, 500)
    order = AbilityOrder("player", "warp_rift", target_position=flagship.position)
    resolve_turn(state, {}, {"player": order})
    assert state.kills["player"] == 1
    assert enemy_id in state.credited_destroyed_ship_ids
```

Using the same explicit state setup, also pin a friendly Warp Rift kill at zero credit, a repeated `_credit_destroyed_ship` call at zero additional credit/event, an environmental/fire death with no author, a normal weapon kill, and two destroyed ships sharing a display name but carrying different IDs.

- [x] **Step 2: Run and confirm red**

Run: `pytest tests/test_campaign_kill_credit.py tests/test_effect_steps.py -q`

Expected: ability kill is uncredited and name-based duplicate-name behavior fails.

- [x] **Step 3: Add only the metadata required by supported area damage**

Add optional `target_ship_id: str | None = None` to `AttackResult` in `combat/resolution.py` and populate it in every resolver that owns the target, including both constructors in `projectile_resolution.py`; this is additive and removes all name lookup from kill credit. Extend `AreaHullDamageHitEvent` with `source_fleet_id` and `target_destroyed`. Set them in `resolve_step` from `ctx.fleet.id` and the before/after alive transition. In `resolve_turn`, inspect emitted command-phase events and pass newly destroyed targets to the identity-based helper. The lance path reads `result.target_ship_id`; the projectile collision path already owns `target.id`.

The helper first checks `credited_destroyed_ship_ids`, then compares the killer fleet/ship faction with the destroyed ship faction. It always emits at most one `DestroyedEvent` and morale side effects per target, but increments a fleet's kills only for an enemy with an attributable owner. Do not redesign general damage attribution.

- [x] **Step 4: Run resolver and XP regressions**

Run: `pytest tests/test_campaign_kill_credit.py tests/test_effect_steps.py tests/test_turn_resolver_movement_phase.py tests/test_battle_end_awards_xp.py -q`

Expected: PASS, including the resolver's existing one-time XP guard.

- [x] **Step 5: Commit**

```bash
git add src/spacefleet/commander/abilities.py src/spacefleet/combat/resolution.py \
  src/spacefleet/combat/projectile_resolution.py src/spacefleet/net/game_state.py \
  src/spacefleet/net/turn_resolver.py tests/test_campaign_kill_credit.py tests/test_effect_steps.py
git commit -m "fix: credit supported ability kills once"
```

**Acceptance:** Weapon and supported ability kills use target identity, never credit friendly/environmental deaths, and never count one target twice.

**Escalate to Astra if:** correct attribution would require a general damage-source system beyond supported `AreaHullDamage`.

---

### Task 5: Atomic campaign economy

**Files:**
- Create: `src/spacefleet/campaign/economy.py`
- Test: `tests/test_campaign_economy.py`

**Interfaces:**
- Consumes: Task 1 state/rules; `ship_points`, normal validation, and catalog costs.
- Produces:
  - `buy_ship(campaign: CampaignState, spec: ShipSpec) -> str` returning the allocated stable ID.
  - `reequip_ship(campaign: CampaignState, ship_id: str, replacement: ShipSpec) -> int` returning net credits charged (negative means refund).
  - `discard_ship(campaign: CampaignState, ship_id: str) -> None`.
  - `repair_ship(campaign: CampaignState, ship_id: str) -> int`.
  - `repair_all(campaign: CampaignState) -> int`.
  - `set_flagship(campaign: CampaignState, ship_id: str) -> None`.
  - `CampaignEconomyError(ValueError)` for readable rejection.

- [x] **Step 1: Write transaction tests**

```python
def test_failed_purchase_does_not_consume_credit_or_id() -> None:
    campaign = campaign_state()
    campaign.credits = 0
    before = deepcopy(campaign)
    with pytest.raises(CampaignEconomyError, match="credits"):
        buy_ship(campaign, deepcopy(supported_fleet().ships[1]))
    assert campaign == before

def test_reequip_refunds_removed_items_per_item_and_preserves_state() -> None:
    campaign = campaign_state()
    saved = campaign.roster[0]
    saved.hull_damage = 2
    saved.battles_survived = 4
    old_cost = WeaponRegistry.get(saved.spec.weapons[3]).cost
    replacement = deepcopy(saved.spec)
    replacement.weapons[3] = "macro_cannon_2"
    new_cost = WeaponRegistry.get("macro_cannon_2").cost
    charged = reequip_ship(campaign, saved.id, replacement)
    assert charged == new_cost - old_cost // 2
    assert saved.hull_damage == 2
    assert saved.battles_survived == 4

def test_repair_all_is_all_or_nothing() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.credits = 15
    before = deepcopy(campaign)
    with pytest.raises(CampaignEconomyError):
        repair_all(campaign)
    assert campaign == before
```

Also cover full-cost purchase, no refund on discard, flagship becoming `None` after loss/discard, explicit flagship reassignment, flagship-only upgrades, removal legality, unsupported equipment, and re-equip rejection when `new_hull_max - hull_damage <= 0`.

- [x] **Step 2: Run and confirm red**

Run: `pytest tests/test_campaign_economy.py -q`

Expected: FAIL on missing module.

- [x] **Step 3: Implement validate-then-commit operations**

Do not add a generic transaction abstraction. Each function computes a candidate and exact charge, validates affordability, calls `validate_campaign_state(candidate)` for interval-safe invariants, and then assigns affected fields and credits in the final lines. `set_flagship` recomputes `FleetSpec.flagship_index` and revalidates flagship-only equipment; pre-battle validation additionally requires a fleet and flagship. Compare equipment by weapon slot plus upgrade IDs plus doctrine; unchanged items produce neither charge nor refund. Hull ID changes in `reequip_ship` are rejected. Discarding the last ship and losing/discarding the flagship are valid interval states; they save successfully, while Task 2 blocks combat until a ship is bought or a flagship selected.

```python
total = sum(ship.hull_damage * REPAIR_COST_PER_HULL for ship in campaign.roster)
if campaign.credits < total:
    raise CampaignEconomyError("insufficient credits")
for ship in campaign.roster:
    ship.hull_damage = 0
campaign.credits -= total
```

- [x] **Step 4: Run focused tests**

Run: `pytest tests/test_campaign_economy.py tests/test_campaign_rules.py tests/test_fleet_spec_validation.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/spacefleet/campaign/economy.py tests/test_campaign_economy.py
git commit -m "feat: add atomic campaign fleet economy"
```

**Acceptance:** Every purchase/refit/discard/repair/flagship operation is atomic, uses the campaign balance, preserves identity/damage/veterancy, and revalidates normal plus campaign legality.

**Escalate to Astra if:** atomicity seems to require pervasive copying or a transaction framework rather than bounded candidate calculation.

---

### Task 6: Idempotent battle closure and five-encounter progression

**Files:**
- Modify: `src/spacefleet/campaign/battle.py`
- Test: `tests/test_campaign_progression.py`

**Interfaces:**
- Consumes: `BattleSession`, `BattleOutcome`, stable/runtime map, and resolver-mutated `Commander`/`Ship` state.
- Produces `BattleReport(battle_id: str, outcome: BattleOutcome, enemy_destroyed: int, player_survivors: int, credits_awarded: int, casualties: Sequence[str], completed_campaign: bool)` and `close_battle(campaign: CampaignState, session: BattleSession, outcome: BattleOutcome) -> BattleReport`.

- [ ] **Step 1: Write closure tests**

```python
def test_victory_copies_resolver_progress_and_rewards_once() -> None:
    campaign = campaign_state()
    session = build_battle(campaign)
    for enemy_id in session.enemy_runtime_ids:
        enemy = session.state.ships[enemy_id]
        enemy.take_hull_damage(enemy.hull_max)
    resolve_turn(session.state, {})
    xp_after_resolver = session.state.fleets["player"].commander.xp
    report = close_battle(campaign, session, BattleOutcome.VICTORY)
    assert report.credits_awarded == 100 + 20 * session.initial_enemy_count + 15 * 2
    assert campaign.commander.xp == xp_after_resolver
    assert campaign.encounter == 2
    before = deepcopy(campaign)
    with pytest.raises(ValueError, match="already resolved"):
        close_battle(campaign, session, BattleOutcome.VICTORY)
    assert campaign == before
```

Also test casualties removed by stable map, hull damage and veterancy copied, commander loadout/XP/level copied without battle-only buffs/cooldowns, destroyed flagship becomes `None`, defeat reward zero/status `DEFEATED`, fifth victory `COMPLETED`, simultaneous elimination defeat, surrender and turn limit no XP addition, and a session for the wrong encounter rejected unchanged.

- [ ] **Step 2: Run and confirm red**

Run: `pytest tests/test_campaign_progression.py -q`

Expected: FAIL on missing report/closure.

- [ ] **Step 3: Implement candidate-first closure**

Reject `ABANDONED`. Verify `session.battle_id`, encounter, active status, and `last_resolved_battle_id` before reading results. Build survivor records by inverting `player_runtime_by_campaign`; calculate reward from `initial_enemy_count` and alive enemy IDs, independent of kill attribution. Copy the already-awarded runtime commander progress once, strip active buffs/runtime ability clocks, then commit roster, commander, credits, encounter/status, and `last_resolved_battle_id` together.

- [ ] **Step 4: Run closure and resolver XP tests**

Run: `pytest tests/test_campaign_progression.py tests/test_battle_end_awards_xp.py tests/test_progression_xp.py tests/test_progression_crew_tier.py -q`

Expected: PASS with no duplicate XP/veterancy.

- [ ] **Step 5: Commit**

```bash
git add src/spacefleet/campaign/battle.py tests/test_campaign_progression.py
git commit -m "feat: close campaign battles idempotently"
```

**Acceptance:** Closure applies casualties, damage, XP, veterancy, reward, encounter/status, and flagship loss once; all defeat variants award nothing; victory five completes the campaign.

**Escalate to Astra if:** resolver end-state cannot distinguish simultaneous elimination from a normal victory without changing `resolve_turn` semantics.

---

### Task 7: Versioned atomic campaign saves

**Files:**
- Create: `src/spacefleet/persistence/campaign_save.py`
- Modify: `src/spacefleet/persistence/__init__.py`
- Test: `tests/test_campaign_save.py`

**Interfaces:**
- Consumes: Task 1 campaign records/rules and `fleet_to_dict`/`fleet_from_dict` shapes for nested `ShipSpec` data.
- Produces `CAMPAIGN_SAVE_VERSION = 1`, `CampaignSaveError(ValueError)`, `campaign_to_dict`, `campaign_from_dict`, `save_campaign(campaign: CampaignState, path: Path) -> Path`, `load_campaign(path: Path) -> CampaignState`, and `default_campaign_path() -> Path` returning `Path.cwd() / "campaign-save.json"`.

- [x] **Step 1: Write round-trip and failure tests**

```python
def test_campaign_round_trip_preserves_stable_state(tmp_path: Path) -> None:
    campaign = campaign_state()
    campaign.commander.xp = 250
    campaign.roster[0].hull_damage = 1
    path = save_campaign(campaign, tmp_path / "campaign.json")
    assert load_campaign(path) == campaign

@pytest.mark.parametrize(
    "payload",
    ["not json", '{"version": 999}'],
)
def test_invalid_or_unknown_save_does_not_replace_current_session(tmp_path, payload) -> None:
    current = campaign_state()
    before = deepcopy(current)
    path = tmp_path / "bad.json"
    path.write_text(payload)
    with pytest.raises(CampaignSaveError):
        load_campaign(path)
    assert current == before

@pytest.mark.parametrize("bad_credit", [True, -1, float("nan"), float("inf"), -float("inf")])
def test_malformed_or_nonfinite_number_is_rejected(tmp_path, bad_credit) -> None:
    data = campaign_to_dict(campaign_state())
    data["credits"] = bad_credit
    path = tmp_path / "bad-number.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CampaignSaveError, match="credits"):
        load_campaign(path)

def test_failed_replace_preserves_old_file_and_retry_succeeds(tmp_path, monkeypatch) -> None:
    original = campaign_state()
    original.credits = 10
    path = save_campaign(original, tmp_path / "campaign.json")
    old_bytes = path.read_bytes()
    replacement = campaign_state()
    replacement.credits = 99
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda source, target: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(CampaignSaveError, match="disk"):
        save_campaign(replacement, path)
    assert path.read_bytes() == old_bytes
    monkeypatch.setattr(os, "replace", real_replace)
    save_campaign(replacement, path)
    assert load_campaign(path).credits == 99
```

Also reject bool-as-int, non-finite floats (`NaN`, positive/negative infinity), negative/out-of-range integers, duplicate/non-monotonic IDs, a non-`None` missing flagship reference, wrong faction, non-empty traits, unsupported equipment/loadout, invalid commander catalog IDs, malformed nested collections, and a stale `next_ship_id`. Add successful round trips for (a) an active interval with surviving ships and `flagship_id=None` after flagship loss, and (b) a terminal defeated campaign with an empty roster. Verify no orphan temp remains after write failure.

- [x] **Step 2: Run and confirm red**

Run: `pytest tests/test_campaign_save.py -q`

Expected: FAIL on missing module.

- [x] **Step 3: Implement strict decoding and invariant validation**

Decode fields with explicit `type(value) is int/str/list/dict` checks and `math.isfinite` for every accepted float before constructing records. Then call `validate_campaign_state(campaign)`—without battle readiness—to validate IDs/references/counter/credits/encounter/status/faction, each ship, campaign eligibility, commander identity/faction/loadout, empty traits, and hull damage against the current catalog maximum. This preserves valid post-loss intervals. Wrap JSON, I/O, enum, catalog, and validation failures in readable `CampaignSaveError` messages containing the path/context.

- [x] **Step 4: Implement same-directory atomic replacement**

```python
fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(campaign_to_dict(campaign), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_name, path)
except OSError as exc:
    Path(temp_name).unlink(missing_ok=True)
    raise CampaignSaveError(f"could not save campaign to {path}: {exc}") from exc
```

Create the parent before the temp file. Never delete or truncate the destination first.

- [x] **Step 5: Run focused persistence tests**

Run: `pytest tests/test_campaign_save.py tests/test_fleet_save.py tests/test_campaign_rules.py -q`

Expected: PASS; existing fleet save format remains unchanged.

- [x] **Step 6: Commit**

```bash
git add src/spacefleet/persistence/campaign_save.py src/spacefleet/persistence/__init__.py \
  tests/test_campaign_save.py
git commit -m "feat: add atomic versioned campaign saves"
```

**Acceptance:** Valid interval state round-trips; malformed/unknown/unsupported saves raise readable errors; failed writes preserve the previous save and permit retry.

**Escalate to Astra if:** supporting a save requires schema migration or accepting an invariant the version-1 spec forbids.

---

### Task 8: Full New/Continue interval, store, autosave, and completion CLI

**Files:**
- Modify: `src/spacefleet/cli/campaign_cmd.py`
- Modify: `src/spacefleet/cli/app.py`
- Test: `tests/test_campaign_cli.py`

**Interfaces:**
- Consumes: all earlier campaign APIs; injected `save_path`, `input_fn`, `output_fn`, and controller factory for tests.
- Produces `run_campaign_menu(*, save_path: Path | None = None, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print, controller_factory: Callable[[BattleSession], LocalBattleController] = LocalBattleController) -> None`; the main app routes one stable menu item to it.

- [ ] **Step 1: Write CLI state-machine tests**

```python
def test_continue_loads_last_interval_and_two_battles_link_through_store(monkeypatch, tmp_path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")

    class WinningController:
        def __init__(self, session: BattleSession) -> None:
            self.session = session

        def run(self) -> BattleOutcome:
            for ship_id in self.session.enemy_runtime_ids:
                ship = self.session.state.ships[ship_id]
                ship.take_hull_damage(ship.hull_max)
            resolve_turn(self.session.state, {})
            return BattleOutcome.VICTORY

    io = ScriptedIO([
        "continue",
        "battle",
        "buy sword_frigate Reinforcement",
        "confirm",
        "battle",
        "back",
    ])
    run_campaign_menu(save_path=path, input_fn=io.input,
                      output_fn=io.output, controller_factory=WinningController)
    loaded = load_campaign(path)
    assert loaded.encounter == 3
    assert any(ship.spec.name == "Reinforcement" for ship in loaded.roster)

def test_new_campaign_cancel_replacement_preserves_existing_save(tmp_path) -> None:
    path = save_campaign(campaign_state(), tmp_path / "save.json")
    old = path.read_bytes()
    io = ScriptedIO(["new", "no", "back"])
    run_campaign_menu(save_path=path, input_fn=io.input, output_fn=io.output)
    assert path.read_bytes() == old
```

Also cover: no-save Continue message; invalid/unknown save leaves current menu/session intact; seed cancellation; unsupported store catalog explanations; discard confirmation cancellation; insufficient-credit errors; explicit save; autosave after each confirmed economy operation; autosave after closure; failed autosave warning plus successful retry; no battle with empty roster or missing flagship; select new flagship after loss; battle quit returns to unchanged interval; victory five and every defeat report terminate cleanly.

- [ ] **Step 2: Run and confirm red**

Run: `pytest tests/test_campaign_cli.py -q`

Expected: FAIL because the initial one-battle seam lacks interval/store/persistence flow.

- [ ] **Step 3: Expand the existing command module into the interval loop**

Keep I/O thin. The interval displays encounter/preset, roster damage and veterancy, commander level/XP/loadout, flagship, and credits. Commands delegate to Task 5 functions: buy, equip/remove weapon/upgrade/doctrine, discard, repair one/all, flagship, battle, save, status/help, back. Before every confirmed destructive action, render the exact cost/refund/loss; cancellation makes no service call.

On New with an existing save, require explicit replacement confirmation before builder work or write. The first save occurs only after a valid initial build. After each successful store operation call `save_campaign`; if save fails, retain the mutated in-memory campaign, print that it is unsaved, and keep `save` available for retry.

On `battle`, call `validate_campaign_state(campaign, require_battle_ready=True)`, build and run a session. For `ABANDONED`, do not call `close_battle` or save. Otherwise close once, print the `BattleReport`, autosave the closed interval/status, and either return to interval, show campaign completion, or show defeat.

- [ ] **Step 4: Run CLI and cross-layer focused tests**

Run: `pytest tests/test_campaign_cli.py tests/test_campaign_economy.py tests/test_campaign_save.py tests/test_local_battle_controller.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/spacefleet/cli/campaign_cmd.py src/spacefleet/cli/app.py tests/test_campaign_cli.py
git commit -m "feat: add campaign interval and continuation flow"
```

**Acceptance:** New/Continue, replacement cancellation, store, repair, flagship selection, battle, reports, retryable saves, five-win completion, and defeat are usable from the local menu with no server.

**Escalate to Astra if:** CLI flow requires a broad UI framework or persistence of live combat state.

---

### Task 9: End-to-end campaign acceptance and repository checks

**Files:**
- Create: `tests/test_campaign_integration.py`
- Modify only if a failure exposes a scoped defect: files owned by Tasks 1-8

**Interfaces:**
- Consumes: public campaign/CLI APIs from Tasks 1-8.
- Produces no new production abstraction.

- [ ] **Step 1: Add the two-battle no-server integration test**

This test must keep the real `LocalBattleController`, `AIController`, and imported `resolve_turn`; it controls positions, target durability, and dice only. It must not monkeypatch the controller or resolver and must close both returned outcomes.

```python
def test_two_real_controller_battles_link_store_and_save_load(
    tmp_path: Path, monkeypatch
) -> None:
    campaign = campaign_state()
    bought_id: str | None = None

    for battle_number in (1, 2):
        session = build_battle(campaign)
        target_id = session.enemy_runtime_ids[0]
        target = session.state.ships[target_id]
        for unused_id in session.enemy_runtime_ids[1:]:
            session.state.ships.pop(unused_id)
            session.state.fleets["enemy"].ship_ids.remove(unused_id)
        session.enemy_runtime_ids[:] = [target_id]
        session.state.player_ships["enemy"] = [target_id]
        session.state.ai_ships = [target_id]
        session.state.fleets["enemy"].ships = [target]
        session.state.fleets["enemy"].flagship_ship_id = target_id
        session.initial_enemy_count = 1
        flagship = session.state.fleets["player"].flagship_in(session.state)
        assert flagship is not None
        flagship.position = Vector2D(0, 0)
        flagship.heading = 0
        target.position = Vector2D(0, 20)
        target.shields_current = 0
        target.hull_current = 1
        target.weapons.clear()
        monkeypatch.setattr(session.state.dice, "roll_d6", lambda count: [6] * count)
        if battle_number == 1:
            flagship.hull_current -= 1

        lines = ["fire 3 0"]
        lines.extend("pass" for _ in session.state.alive_ships_for("player")[1:])
        lines.extend(["ability skip", "review", "confirm"])
        io = ScriptedIO(lines)
        outcome = LocalBattleController(
            session, input_fn=io.input, output_fn=io.output
        ).run()
        assert outcome is BattleOutcome.VICTORY
        close_battle(campaign, session, outcome)

        if battle_number == 1:
            assert campaign.roster[0].hull_damage == 1
            repair_ship(campaign, campaign.roster[0].id)
            reinforcement = deepcopy(supported_fleet().ships[1])
            reinforcement.name = "Reinforcement"
            bought_id = buy_ship(campaign, reinforcement)
            path = save_campaign(campaign, tmp_path / "campaign.json")
            campaign = load_campaign(path)

    assert campaign.encounter == 3
    assert bought_id is not None
    assert any(ship.id == bought_id for ship in campaign.roster)
```

Add one parametrized five-result progression test that closes four victories then verifies the fifth victory completes, while defeat variants stop without duplicate awards. Do not duplicate lower-level validation already covered by focused tests.

- [ ] **Step 2: Run campaign tests first**

Run: `pytest tests/test_campaign_rules.py tests/test_campaign_battle.py tests/test_local_battle_controller.py tests/test_campaign_kill_credit.py tests/test_campaign_economy.py tests/test_campaign_progression.py tests/test_campaign_save.py tests/test_campaign_cli.py tests/test_campaign_integration.py -q`

Expected: PASS.

- [ ] **Step 3: Run required repository checks once**

Run:

```bash
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync mypy src
uv run --no-sync pytest
```

Expected: PASS. Record any pre-existing failure separately with the exact command and evidence that the campaign-focused suite remains green; do not broaden this feature into unrelated cleanup.

- [ ] **Step 4: Perform the required short manual play**

Run: `python -m spacefleet`.

Manual checklist:

1. Start New, cancel once, then start with each faction and an explicit seed.
2. Build a supported fleet under 800, confirm initial balance, and verify unsupported catalog entries explain why unavailable.
3. In battle use status/scan/weapons/help, reject one invalid order, queue a stance, order movement/fire/boarding, submit one supported ability, review/revise, then confirm.
4. Quit once and Continue to prove the previous interval remains; replay the same seed/orders and compare the outcome.
5. Finish a short controlled victory, inspect damage/XP/credits/casualties, repair and buy, save, restart, and Continue.
6. Exercise surrender or a controlled defeat and verify zero reward and a clear final report.

- [ ] **Step 5: Commit acceptance coverage**

```bash
git add tests/test_campaign_integration.py
git commit -m "test: cover campaign progression end to end"
```

**Acceptance:** The three spec deliverables pass: a local manual battle from the menu, two linked battles with store/progression, and save/continue through final victory or defeat without duplicate awards.

**Escalate to Astra if:** full checks reveal an architectural conflict, repeated non-local failures, or the implementation materially exceeds this plan's module/task boundaries.

---

## Execution and review gate

Do not begin implementation until the user reviews and approves this plan. After approval, Astra assigns each task to a bounded Sol worker in order, requests Terra review for the completed task, resolves findings, and advances only after its acceptance criteria and targeted tests pass. Astra performs the final spec-coverage/type review and accepts the full required-check output.
