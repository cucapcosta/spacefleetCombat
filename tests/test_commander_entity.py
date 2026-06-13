"""Commander dataclass + AbilityState + ActiveBuff construction."""

from __future__ import annotations

from spacefleet.commander.commander import (
    AbilityState,
    ActiveBuff,
    Commander,
)
from spacefleet.core.types import Faction


def test_commander_defaults() -> None:
    c = Commander(id="c1", name="Admiral", faction=Faction.IMPERIAL_NAVY)
    assert c.level == 1
    assert c.xp == 0
    assert c.active_ability_ids == []
    assert c.passive_skill_ids == []
    assert c.trait_ids == []
    assert c.ability_state == {}
    assert c.active_buffs == []


def test_ability_state_defaults() -> None:
    st = AbilityState(remaining_charges=3)
    assert st.remaining_charges == 3
    assert st.cooldown_remaining == 0
    assert st.preparation_turns_left == 0
    assert st.pending_order is None


def test_active_buff_defaults() -> None:
    buff = ActiveBuff(
        id="mark_of_chaos",
        source_ability_id="mark_of_chaos",
        turns_remaining=3,
    )
    assert buff.data == {}
