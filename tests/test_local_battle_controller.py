from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from spacefleet.campaign.battle import BattleSession, build_battle
from spacefleet.campaign.models import BattleOutcome
from spacefleet.cli import campaign_cmd, local_battle
from spacefleet.cli.action_parser import parse_action_command
from spacefleet.cli.local_battle import LocalBattleController
from spacefleet.commander.commander import AbilityState
from spacefleet.core.types import Stance
from spacefleet.net.commands import AbilityOrder, Command
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.net.turn_resolver import TurnLog
from spacefleet.phases.command_phase import AbilityRejectedEvent
from tests.campaign_helpers import ScriptedIO, campaign_state, supported_fleet

if TYPE_CHECKING:
    import pytest

    from spacefleet.net.game_state import GameState


class RecordingAI(local_battle.AIController):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def generate_commands(
        self,
        state: GameState,
        controlled_ids: list[str] | None = None,
    ) -> dict[str, Command]:
        ids = list(controlled_ids or [])
        self.calls.append((ids, state.turn))
        return {ship_id: Command(ship_id=ship_id, action="pass") for ship_id in ids}


def _destroy_enemies(session: BattleSession) -> None:
    for ship_id in session.enemy_runtime_ids:
        ship = session.state.ships[ship_id]
        ship.take_hull_damage(ship.hull_max)


def test_action_parser_preserves_commands_and_rejects_nonfinite_numbers() -> None:
    parsed = parse_action_command("ship-1", ["fire", "2", "90"])
    assert not isinstance(parsed, str)
    assert parsed["action"] == "fire"
    assert parsed["args"] == {"slot": 2, "bearing": 90.0}

    for tokens in (["ahead", "nan"], ["turn", "port", "inf"], ["fire", "1", "-inf"]):
        assert isinstance(parse_action_command("ship-1", tokens), str)


def test_invalid_and_query_input_do_not_advance_then_ability_reaches_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_battle(campaign_state())
    seen: list[dict[str, AbilityOrder]] = []
    enemy_id = session.enemy_runtime_ids[0]
    flagship = session.state.fleets["player"].flagship_in(session.state)
    assert flagship is not None
    session.state.ships[enemy_id].position = flagship.position

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        seen.append(ability_orders)
        _destroy_enemies(session)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    io = ScriptedIO(
        [
            "status",
            "fire nope",
            "pass",
            "pass",
            "ability concentrated_fire at nan 0",
            f"ability concentrated_fire {enemy_id}",
            "review",
            "confirm",
        ]
    )

    outcome = LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    assert outcome is BattleOutcome.VICTORY
    assert session.state.turn == 1
    order = seen[0]["player"]
    assert order.ability_id == "concentrated_fire"
    assert "Invalid" in "\n".join(io.outputs)


def test_ai_receives_only_explicit_enemy_ids_after_turn_increment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_battle(campaign_state())
    ai = RecordingAI()
    monkeypatch.setattr(
        local_battle,
        "resolve_turn",
        lambda state, commands, ability_orders: TurnLog(turn=state.turn),
    )
    io = ScriptedIO(["pass", "pass", "ability skip", "confirm", "quit"])

    outcome = LocalBattleController(
        session,
        input_fn=io.input,
        output_fn=io.output,
        ai=ai,
    ).run()

    assert outcome is BattleOutcome.ABANDONED
    assert ai.calls == [(session.enemy_runtime_ids, 1)]


def test_queued_stance_changes_only_on_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    player_id = session.state.player_ships["player"][0]
    stance_during_resolution: list[Stance] = []

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        stance_during_resolution.append(state.ships[player_id].stance)
        _destroy_enemies(session)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    io = ScriptedIO(["stance lock_on", "pass", "pass", "ability skip", "confirm"])

    LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    assert stance_during_resolution == [Stance.LOCK_ON]


def test_revise_discards_queued_stances(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    player_id = session.state.player_ships["player"][0]
    stance_during_resolution: list[Stance] = []

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        stance_during_resolution.append(state.ships[player_id].stance)
        _destroy_enemies(session)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    io = ScriptedIO(
        [
            "stance lock_on",
            "pass",
            "pass",
            "ability skip",
            "revise",
            "pass",
            "pass",
            "ability skip",
            "confirm",
        ]
    )

    LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    assert stance_during_resolution == [Stance.STANDARD]


def test_cooldown_one_ability_is_accepted_before_resolver_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_battle(campaign_state())
    commander = session.state.fleets["player"].commander
    assert commander is not None
    commander.ability_state["concentrated_fire"] = AbilityState(
        remaining_charges=1,
        cooldown_remaining=1,
    )
    enemy_id = session.enemy_runtime_ids[0]
    flagship = session.state.fleets["player"].flagship_in(session.state)
    assert flagship is not None
    session.state.ships[enemy_id].position = flagship.position
    seen: list[dict[str, AbilityOrder]] = []

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        seen.append(ability_orders)
        _destroy_enemies(session)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    io = ScriptedIO(["pass", "pass", f"ability concentrated_fire {enemy_id}", "confirm"])

    LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    assert "player" in seen[0]


def test_resolution_ability_rejection_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    enemy_id = session.enemy_runtime_ids[0]
    flagship = session.state.fleets["player"].flagship_in(session.state)
    assert flagship is not None
    session.state.ships[enemy_id].position = flagship.position

    def reject_during_resolution(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        _destroy_enemies(session)
        return TurnLog(
            turn=state.turn,
            events=[
                AbilityRejectedEvent(
                    ability_id="concentrated_fire",
                    fleet_id="player",
                    reason="target_missing",
                )
            ],
        )

    monkeypatch.setattr(local_battle, "resolve_turn", reject_during_resolution)
    io = ScriptedIO(["pass", "pass", f"ability concentrated_fire {enemy_id}", "confirm"])

    LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    output = "\n".join(io.outputs)
    assert "concentrated_fire" in output
    assert "target_missing" in output


def test_same_seed_and_orders_produce_equivalent_state_and_rendering() -> None:
    first = build_battle(campaign_state())
    second = build_battle(campaign_state())
    first_io = ScriptedIO(["pass", "pass", "ability skip", "confirm", "quit"])
    second_io = ScriptedIO(["pass", "pass", "ability skip", "confirm", "quit"])

    LocalBattleController(first, input_fn=first_io.input, output_fn=first_io.output).run()
    LocalBattleController(second, input_fn=second_io.input, output_fn=second_io.output).run()

    first_state = [
        (ship.id, ship.position, ship.heading, ship.speed, ship.hull_current, ship.shields_current)
        for ship in first.state.ships.values()
    ]
    second_state = [
        (ship.id, ship.position, ship.heading, ship.speed, ship.hull_current, ship.shields_current)
        for ship in second.state.ships.values()
    ]
    assert first_state == second_state
    assert first_io.outputs == second_io.outputs


def test_surrender_and_quit_end_without_resolving() -> None:
    surrender = build_battle(campaign_state())
    surrendered = LocalBattleController(
        surrender,
        input_fn=ScriptedIO(["surrender"]).input,
        output_fn=lambda _text: None,
    ).run()
    assert surrendered is BattleOutcome.SURRENDER
    assert surrender.state.turn == 0

    campaign = campaign_state()
    before = deepcopy(campaign)
    abandoned = LocalBattleController(
        build_battle(campaign),
        input_fn=ScriptedIO(["quit"]).input,
        output_fn=lambda _text: None,
    ).run()
    assert abandoned is BattleOutcome.ABANDONED
    assert campaign == before


def test_help_explains_local_battle_syntax() -> None:
    session = build_battle(campaign_state())
    io = ScriptedIO(["help", "quit"])

    LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    output = "\n".join(io.outputs)
    assert "fire <weapon#> <bearing>" in output
    assert "stance <name>" in output
    assert "ability <ability_id>" in output
    assert "review" in output


def test_turn_limit_stops_after_completed_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    monkeypatch.setattr(
        local_battle,
        "resolve_turn",
        lambda state, commands, ability_orders: TurnLog(turn=state.turn),
    )
    io = ScriptedIO(["pass", "pass", "ability skip", "confirm"])

    outcome = LocalBattleController(
        session,
        input_fn=io.input,
        output_fn=io.output,
        turn_limit=1,
    ).run()

    assert outcome is BattleOutcome.TURN_LIMIT
    assert session.state.turn == 1


def test_simultaneous_elimination_is_a_defeat(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())

    def eliminate_both(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        for ship_id in state.player_ships["player"] + session.enemy_runtime_ids:
            ship = state.ships[ship_id]
            ship.take_hull_damage(ship.hull_max)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", eliminate_both)
    io = ScriptedIO(["pass", "pass", "ability skip", "confirm"])

    outcome = LocalBattleController(session, input_fn=io.input, output_fn=io.output).run()

    assert outcome is BattleOutcome.DEFEAT


def test_default_renderer_outputs_turn_events(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    player_ship = session.state.ships[session.state.player_ships["player"][0]]

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        from spacefleet.net.turn_resolver import SpeedChangeEvent

        _destroy_enemies(session)
        return TurnLog(
            turn=state.turn,
            events=[SpeedChangeEvent(ship=player_ship, old_speed=0, new_speed=5)],
        )

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    io = ScriptedIO(["pass", "pass", "ability skip", "confirm"])

    LocalBattleController(
        session,
        input_fn=io.input,
        output_fn=io.output,
        renderer=ServerRenderer(),
    ).run()

    assert "Speed" in "\n".join(io.outputs)


def test_run_new_campaign_builds_and_runs_first_battle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fleet = supported_fleet()
    seen: dict[str, BattleSession] = {}
    answers = iter(["1", "Admiral Voss", "19"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", lambda **_kwargs: fleet)

    class Controller:
        def __init__(self, session: BattleSession) -> None:
            seen["session"] = session

        def run(self) -> BattleOutcome:
            return BattleOutcome.ABANDONED

    monkeypatch.setattr(campaign_cmd, "LocalBattleController", Controller)

    campaign_cmd.run_new_campaign()

    session = seen["session"]
    assert session.battle_id == "19:1"
    commander = session.state.fleets["player"].commander
    assert commander is not None
    assert commander.name == "Admiral Voss"


def test_app_menu_mentions_local_campaign() -> None:
    from spacefleet.cli.app import MENU

    assert "Campaign" in MENU
