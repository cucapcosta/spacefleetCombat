"""PassiveBus dispatch semantics: aggregation, overrides, default."""

from __future__ import annotations

from spacefleet.commander.passive_skills import (
    PassiveBus,
    PassiveContext,
    PassiveHook,
)
from spacefleet.core.game_state import CoreGameState


def test_dispatch_with_no_handlers_returns_default() -> None:
    state = CoreGameState()
    bus = PassiveBus.build(state)
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=0)
    result = bus.dispatch(PassiveHook.FLEET_SPEED_MAX, ctx)
    assert result == 0


def test_register_and_sum_contributions() -> None:
    state = CoreGameState()
    bus = PassiveBus.build(state)
    bus.register(
        source="test_a",
        hook=PassiveHook.FLEET_SPEED_MAX,
        handler=lambda ctx: ctx.value + 5,
    )
    bus.register(
        source="test_b",
        hook=PassiveHook.FLEET_SPEED_MAX,
        handler=lambda ctx: ctx.value + 3,
    )
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=0)
    assert bus.dispatch(PassiveHook.FLEET_SPEED_MAX, ctx) == 8


def test_override_hook_first_writer_wins() -> None:
    state = CoreGameState()
    bus = PassiveBus.build(state)
    bus.register(
        source="a",
        hook=PassiveHook.LANCE_HIT_THRESHOLD,
        handler=lambda ctx: 3,
    )
    bus.register(
        source="b",
        hook=PassiveHook.LANCE_HIT_THRESHOLD,
        handler=lambda ctx: 2,
    )
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=None)
    assert bus.dispatch(PassiveHook.LANCE_HIT_THRESHOLD, ctx) == 3


def test_override_hook_none_when_no_handlers() -> None:
    state = CoreGameState()
    bus = PassiveBus.build(state)
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=None)
    assert bus.dispatch(PassiveHook.LANCE_HIT_THRESHOLD, ctx) is None
