from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.economy import (
    REPAIR_COST_PER_HULL,
    CampaignEconomyError,
    buy_ship,
    discard_ship,
    reequip_ship,
    repair_all,
    repair_ship,
    set_flagship,
)
from spacefleet.campaign.models import CampaignStatus
from spacefleet.campaign.rules import validate_campaign_state
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import ship_points
from tests.campaign_helpers import campaign_state, supported_fleet

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.campaign.models import CampaignState


def test_failed_purchase_does_not_consume_credit_or_id() -> None:
    campaign = campaign_state()
    campaign.credits = 0
    reinforcement = deepcopy(supported_fleet().ships[1])
    reinforcement.name = "Second Escort"
    before = deepcopy(campaign)

    with pytest.raises(CampaignEconomyError, match="credits"):
        buy_ship(campaign, reinforcement)

    assert campaign == before


def test_purchase_charges_full_cost_and_allocates_next_stable_id() -> None:
    campaign = campaign_state()
    campaign.credits = 500
    reinforcement = deepcopy(supported_fleet().ships[1])
    reinforcement.name = "Second Escort"
    expected_cost = ship_points(reinforcement)

    ship_id = buy_ship(campaign, reinforcement)

    assert ship_id == "ship-3"
    assert campaign.next_ship_id == 4
    assert campaign.credits == 500 - expected_cost
    assert campaign.roster[-1].id == ship_id
    assert campaign.roster[-1].hull_damage == 0
    assert campaign.roster[-1].battles_survived == 0
    reinforcement.name = "Changed outside campaign"
    assert campaign.roster[-1].spec.name == "Second Escort"


def test_reequip_refunds_removed_items_per_item_and_preserves_state() -> None:
    campaign = campaign_state()
    campaign.credits = 500
    saved = campaign.roster[0]
    saved.hull_damage = 2
    saved.battles_survived = 4
    old_cost = WeaponRegistry.get(saved.spec.weapons[3]).cost
    replacement = deepcopy(saved.spec)
    replacement.weapons[3] = "macro_cannon_2"
    new_cost = WeaponRegistry.get("macro_cannon_2").cost

    charged = reequip_ship(campaign, saved.id, replacement)

    assert charged == new_cost - old_cost // 2
    assert campaign.credits == 500 - charged
    assert saved.hull_damage == 2
    assert saved.battles_survived == 4


def test_reequip_refunds_each_removed_item_and_ignores_unchanged_items() -> None:
    campaign = campaign_state()
    campaign.credits = 500
    saved = campaign.roster[0]
    saved.spec.upgrade_ids = ["reinforced_prow", "navigators_chamber"]
    saved.spec.doctrine_id = "commissariat"
    validate_campaign_state(campaign)
    replacement = deepcopy(saved.spec)
    replacement.name = "Renamed Flag"
    replacement.weapons.pop(3)
    replacement.upgrade_ids.remove("reinforced_prow")
    replacement.doctrine_id = None
    expected_refund = (
        WeaponRegistry.get("lance_2").cost // 2
        + UpgradeRegistry.get("reinforced_prow").cost // 2
        + DoctrineRegistry.get("commissariat").cost // 2
    )

    charged = reequip_ship(campaign, saved.id, replacement)

    assert charged == -expected_refund
    assert campaign.credits == 500 + expected_refund
    assert saved.spec == replacement


def test_reequip_identical_equipment_does_not_charge_or_heal() -> None:
    campaign = campaign_state()
    campaign.credits = 100
    saved = campaign.roster[0]
    saved.hull_damage = 2
    replacement = deepcopy(saved.spec)
    replacement.name = "Renamed Flag"

    charged = reequip_ship(campaign, saved.id, replacement)

    assert charged == 0
    assert campaign.credits == 100
    assert saved.hull_damage == 2
    assert saved.spec.name == "Renamed Flag"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda campaign: setattr(campaign.roster[0].spec, "name", "Test Escort"), "duplicate"),
        (
            lambda campaign: campaign.roster[0].spec.weapons.__setitem__(3, "standard_torpedoes"),
            "torpedo",
        ),
        (
            lambda campaign: campaign.roster[1].spec.upgrade_ids.append("navigators_chamber"),
            "flagship",
        ),
    ],
)
def test_invalid_purchase_preserves_campaign(
    change: Callable[[CampaignState], None], message: str
) -> None:
    campaign = campaign_state()
    campaign.credits = 500
    source = campaign_state()
    change(source)
    spec = deepcopy(source.roster[0 if message != "flagship" else 1].spec)
    if message != "duplicate":
        spec.name = "Incoming Invalid"
    before = deepcopy(campaign)

    with pytest.raises(CampaignEconomyError, match=message):
        buy_ship(campaign, spec)

    assert campaign == before


def test_illegal_equipment_removal_preserves_campaign() -> None:
    campaign = campaign_state()
    saved = campaign.roster[1]
    saved.spec.doctrine_id = "mechanicus_rites"
    saved.spec.upgrade_ids = ["reinforced_prow", "crew_quarters"]
    validate_campaign_state(campaign)
    replacement = deepcopy(saved.spec)
    replacement.doctrine_id = None
    before = deepcopy(campaign)

    with pytest.raises(CampaignEconomyError, match="slots"):
        reequip_ship(campaign, saved.id, replacement)

    assert campaign == before


def test_reequip_rejects_hull_change_and_lethal_effective_hull_atomically() -> None:
    campaign = campaign_state(Faction.CHAOS_FLEET)
    saved = campaign.roster[1]
    saved.spec.doctrine_id = "mark_of_nurgle"
    saved.hull_damage = HullRegistry.get(saved.spec.hull_id).hull_hits
    validate_campaign_state(campaign)

    changed_hull = deepcopy(saved.spec)
    changed_hull.hull_id = "slaughter_cruiser"
    before = deepcopy(campaign)
    with pytest.raises(CampaignEconomyError, match="hull"):
        reequip_ship(campaign, saved.id, changed_hull)
    assert campaign == before

    lethal = deepcopy(saved.spec)
    lethal.doctrine_id = None
    with pytest.raises(CampaignEconomyError, match="hull"):
        reequip_ship(campaign, saved.id, lethal)
    assert campaign == before


def test_discard_has_no_refund_and_clears_flagship() -> None:
    campaign = campaign_state()
    credits = campaign.credits

    discard_ship(campaign, campaign.flagship_id or "")

    assert campaign.credits == credits
    assert [ship.id for ship in campaign.roster] == ["ship-2"]
    assert campaign.flagship_id is None
    assert campaign.next_ship_id == 3


def test_discarding_last_ship_is_a_valid_interval_state() -> None:
    campaign = campaign_state()
    discard_ship(campaign, "ship-2")
    discard_ship(campaign, "ship-1")

    assert campaign.roster == []
    assert campaign.flagship_id is None
    validate_campaign_state(campaign)


def test_repair_ship_charges_eight_per_hull_and_is_all_or_nothing() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.credits = 16

    charged = repair_ship(campaign, "ship-1")

    assert charged == 2 * REPAIR_COST_PER_HULL == 16
    assert campaign.credits == 0
    assert campaign.roster[0].hull_damage == 0

    campaign.roster[0].hull_damage = 1
    before = deepcopy(campaign)
    with pytest.raises(CampaignEconomyError, match="credits"):
        repair_ship(campaign, "ship-1")
    assert campaign == before


def test_repair_all_is_all_or_nothing() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    campaign.credits = 15
    before = deepcopy(campaign)

    with pytest.raises(CampaignEconomyError, match="credits"):
        repair_all(campaign)

    assert campaign == before

    campaign.credits = 16
    charged = repair_all(campaign)
    assert charged == 16
    assert campaign.credits == 0
    assert [ship.hull_damage for ship in campaign.roster] == [0, 0]


def test_set_flagship_revalidates_exclusive_equipment_atomically() -> None:
    campaign = campaign_state()
    campaign.roster[0].spec.upgrade_ids.append("navigators_chamber")
    validate_campaign_state(campaign)
    before = deepcopy(campaign)

    with pytest.raises(CampaignEconomyError, match="flagship"):
        set_flagship(campaign, "ship-2")

    assert campaign == before

    campaign.roster[0].spec.upgrade_ids.clear()
    set_flagship(campaign, "ship-2")
    assert campaign.flagship_id == "ship-2"


def test_unknown_ship_operations_preserve_campaign() -> None:
    operations: list[Callable[[CampaignState], object]] = [
        lambda campaign: reequip_ship(campaign, "ship-99", deepcopy(campaign.roster[0].spec)),
        lambda campaign: discard_ship(campaign, "ship-99"),
        lambda campaign: repair_ship(campaign, "ship-99"),
        lambda campaign: set_flagship(campaign, "ship-99"),
    ]
    for operation in operations:
        campaign = campaign_state()
        before = deepcopy(campaign)
        with pytest.raises(CampaignEconomyError, match="ship"):
            operation(campaign)
        assert campaign == before


@pytest.mark.parametrize("status", [CampaignStatus.COMPLETED, CampaignStatus.DEFEATED])
def test_economy_operations_reject_ended_campaigns(status: CampaignStatus) -> None:
    operations: list[Callable[[CampaignState], object]] = [
        lambda campaign: buy_ship(campaign, deepcopy(supported_fleet().ships[1])),
        lambda campaign: reequip_ship(campaign, "ship-1", deepcopy(campaign.roster[0].spec)),
        lambda campaign: discard_ship(campaign, "ship-1"),
        lambda campaign: repair_ship(campaign, "ship-1"),
        lambda campaign: repair_all(campaign),
        lambda campaign: set_flagship(campaign, "ship-2"),
    ]
    for operation in operations:
        campaign = campaign_state()
        campaign.status = status
        before = deepcopy(campaign)
        with pytest.raises(CampaignEconomyError, match="active"):
            operation(campaign)
        assert campaign == before
