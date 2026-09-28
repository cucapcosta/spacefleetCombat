from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.battle import BattleSession, build_battle
from spacefleet.campaign.models import BattleOutcome
from spacefleet.cli import campaign_cmd, local_battle
from spacefleet.cli.action_parser import parse_action_command
from spacefleet.cli.display import format_contact
from spacefleet.cli.local_battle import LocalBattleController
from spacefleet.core.types import Arc, DetectionLevel, Vector2D
from spacefleet.net.commands import AbilityOrder, Command
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.net.turn_resolver import TurnLog
from spacefleet.spatial.detection import ContactInfo
from spacefleet.spatial.geometry import arc_range_str, is_in_arc
from tests.campaign_helpers import campaign_state, supported_fleet
from tests.terminal_ui_helpers import FakeTerminalUI

if TYPE_CHECKING:
    from pathlib import Path

    from spacefleet.net.game_state import GameState


class RecordingAI(local_battle.AIController):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def generate_commands(
        self, state: GameState, controlled_ids: list[str] | None = None
    ) -> dict[str, Command]:
        ids = list(controlled_ids or [])
        self.calls.append((ids, state.turn))
        return {ship_id: Command(ship_id=ship_id, action="pass") for ship_id in ids}


def test_action_parser_preserves_commands_and_rejects_nonfinite_numbers() -> None:
    parsed = parse_action_command("ship-1", ["fire", "2", "90"])
    assert not isinstance(parsed, str)
    assert parsed["action"] == "fire"
    assert parsed["args"] == {"slot": 2, "bearing": 90.0}
    for tokens in (["ahead", "nan"], ["turn", "port", "inf"], ["fire", "1", "-inf"]):
        assert isinstance(parse_action_command("ship-1", tokens), str)


def test_prow_arc_label_matches_the_actual_plus_or_minus_45_degree_rule() -> None:
    assert arc_range_str(Arc.PROW) == "315°–045° rel"
    assert is_in_arc(0, 315, Arc.PROW)
    assert is_in_arc(0, 45, Arc.PROW)
    assert not is_in_arc(0, 46, Arc.PROW)


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
    ui = FakeTerminalUI(choices=["wait", "wait", "ability:none", "confirm"])

    outcome = LocalBattleController(session, ui=ui, ai=ai, turn_limit=1).run()

    assert outcome is BattleOutcome.TURN_LIMIT
    assert ai.calls == [(session.enemy_runtime_ids, 1)]


@pytest.mark.parametrize("level", [DetectionLevel.CONTACT, DetectionLevel.IDENTIFIED])
def test_targetable_sensor_contact_shows_runtime_target_id(level: DetectionLevel) -> None:
    session = build_battle(campaign_state())
    observer = session.state.ships[session.state.player_ships[session.player_id][0]]
    target = session.state.ships[session.enemy_runtime_ids[0]]
    contact = ContactInfo(
        ship=target,
        detection_level=level,
        true_distance=20.0,
        true_bearing=0.0,
        display_position=target.position,
        display_name="Escort-class" if level is DetectionLevel.CONTACT else target.name,
        targetable=True,
        accuracy_penalty=level is DetectionLevel.CONTACT,
    )
    assert f"id={target.id}" in format_contact(target, observer, contact_info=contact)


def test_blip_contact_does_not_reveal_runtime_id_or_identity() -> None:
    session = build_battle(campaign_state())
    observer = session.state.ships[session.state.player_ships[session.player_id][0]]
    target = session.state.ships[session.enemy_runtime_ids[0]]
    contact = ContactInfo(
        ship=target,
        detection_level=DetectionLevel.BLIP,
        true_distance=100.0,
        true_bearing=0.0,
        display_position=Vector2D(0.0, 100.0),
        display_name="Unknown contact",
        targetable=False,
        accuracy_penalty=False,
    )
    rendered = format_contact(target, observer, contact_info=contact)
    assert target.id not in rendered
    assert target.name not in rendered
    assert "Unknown contact" in rendered


def test_ship_brief_does_not_reveal_undetected_enemy_id() -> None:
    session = build_battle(campaign_state())
    observer = session.state.ships[session.state.player_ships[session.player_id][0]]
    for enemy_id in session.enemy_runtime_ids:
        session.state.ships[enemy_id].position = Vector2D(10_000.0, 10_000.0)
    rendered = ServerRenderer().preview_ship_brief(observer, session.state, session.player_id)
    assert all(enemy_id not in rendered for enemy_id in session.enemy_runtime_ids)


def test_simultaneous_elimination_is_a_defeat(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())

    def eliminate_both(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        for ship_id in state.player_ships["player"] + session.enemy_runtime_ids:
            state.ships[ship_id].take_hull_damage(state.ships[ship_id].hull_max)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", eliminate_both)
    ui = FakeTerminalUI(choices=["wait", "wait", "ability:none", "confirm"])
    assert LocalBattleController(session, ui=ui).run() is BattleOutcome.DEFEAT


def test_default_renderer_outputs_turn_events(monkeypatch: pytest.MonkeyPatch) -> None:
    session = build_battle(campaign_state())
    player_ship = session.state.ships[session.state.player_ships["player"][0]]

    def resolve_once(
        state: GameState,
        commands: dict[str, Command],
        ability_orders: dict[str, AbilityOrder],
    ) -> TurnLog:
        from spacefleet.net.turn_resolver import SpeedChangeEvent

        for ship_id in session.enemy_runtime_ids:
            state.ships[ship_id].take_hull_damage(state.ships[ship_id].hull_max)
        return TurnLog(
            turn=state.turn,
            events=[SpeedChangeEvent(ship=player_ship, old_speed=0, new_speed=5)],
        )

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    ui = FakeTerminalUI(choices=["wait", "wait", "ability:none", "confirm"])
    LocalBattleController(session, ui=ui).run()
    assert "Speed" in "\n".join(ui.show_calls)


def test_run_campaign_menu_builds_and_runs_first_battle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fleet = supported_fleet()
    seen: dict[str, BattleSession] = {}
    monkeypatch.setattr(campaign_cmd, "run_fleet_builder", lambda **_kwargs: fleet)

    class Controller(LocalBattleController):
        def __init__(self, session: BattleSession) -> None:
            seen["session"] = session

        def run(self) -> BattleOutcome:
            return BattleOutcome.ABANDONED

    ui = FakeTerminalUI(
        choices=["new", "imperial_navy", "battle", "back"],
        texts=["Admiral Voss", "19"],
    )
    campaign_cmd.run_campaign_menu(
        save_path=tmp_path / "campaign.json", ui=ui, controller_factory=Controller
    )
    assert seen["session"].battle_id == "19:1"
    commander = seen["session"].state.fleets["player"].commander
    assert commander is not None
    assert commander.name == "Admiral Voss"


def test_app_menu_mentions_local_campaign() -> None:
    from spacefleet.cli.app import MENU

    assert "Campaign" in MENU
