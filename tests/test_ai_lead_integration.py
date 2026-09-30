"""End to end: the AI maneuvers and fires in one turn, and its lead hits."""

from __future__ import annotations

import pytest

from spacefleet.campaign.battle import build_battle
from spacefleet.core.types import Vector2D
from spacefleet.net import turn_resolver
from spacefleet.net.ai_controller import AIController
from spacefleet.net.turn_resolver import SalvoImpactEvent, resolve_turn
from tests.campaign_helpers import campaign_state


@pytest.fixture
def no_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_resolver, "bearing_spread", lambda *_args: 0.0)


@pytest.mark.usefixtures("no_spread")
def test_ai_maneuvers_and_hits_a_target_holding_course() -> None:
    session = build_battle(campaign_state())
    state = session.state
    ai_id = session.enemy_runtime_ids[0]
    ai_ship = state.ships[ai_id]
    target = state.ships[state.player_ships[session.player_id][0]]
    for other in state.ships.values():  # keep the duel to these two ships
        if other.id not in (ai_id, target.id):
            other.position = Vector2D(500.0, 500.0)
    ai_ship.position = Vector2D(0.0, 0.0)
    ai_ship.heading = 0.0
    ai_ship.speed = 4.0
    # Escort guns bear through the prow: the target crosses ahead of it.
    target.position = Vector2D(-4.0, 18.0)
    target.heading = 90.0
    target.speed = 6.0

    commands = AIController(fire_chance=1.0).generate_commands(state, controlled_ids=[ai_id])
    order = commands[ai_id]
    assert order.action == "fire"
    assert order.maneuver is not None

    start = ai_ship.position
    impacts: list[SalvoImpactEvent] = []
    for turn in range(3):
        log = resolve_turn(state, commands if turn == 0 else {})
        impacts.extend(e for e in log.events if isinstance(e, SalvoImpactEvent))
        if turn == 0:
            assert ai_ship.position != start  # maneuvered in the same turn it fired

    assert any(e.target.id == target.id for e in impacts)
