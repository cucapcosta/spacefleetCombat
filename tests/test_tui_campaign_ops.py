"""Detached campaign candidates used by the campaign and hangar screens."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.economy import CampaignEconomyError
from spacefleet.tui.model.campaign_ops import (
    autosave,
    credit_change,
    hull_offers,
    quote_refit,
    quote_repair_all,
    quote_repair_ship,
)
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from pathlib import Path


def test_credit_change_wording() -> None:
    assert credit_change(8) == "charge 8 credits"
    assert credit_change(-12) == "refund 12 credits"
    assert credit_change(0) == "no credit change"


def test_quote_refit_is_detached_and_priced() -> None:
    campaign = campaign_state()
    before = deepcopy(campaign)
    replacement = deepcopy(campaign.roster[0].spec)
    replacement.weapons[3] = "macro_cannon_2"
    quote = quote_refit(campaign, "ship-1", replacement)
    assert campaign == before
    assert quote.candidate is not None
    assert quote.charge == 8
    assert quote.balance == campaign.credits - 8
    assert "charge 8 credits" in quote.preview


def test_quote_refit_unaffordable_has_reason_and_no_candidate() -> None:
    campaign = campaign_state()
    campaign.credits = 0
    replacement = deepcopy(campaign.roster[0].spec)
    replacement.weapons[3] = "macro_cannon_2"
    quote = quote_refit(campaign, "ship-1", replacement)
    assert quote.candidate is None
    assert quote.reason == "insufficient credits"
    assert quote.balance == -8


def test_quote_refit_illegal_raises() -> None:
    campaign = campaign_state()
    replacement = deepcopy(campaign.roster[0].spec)
    replacement.hull_id = "sword_frigate"
    with pytest.raises(CampaignEconomyError):
        quote_refit(campaign, "ship-1", replacement)


def test_hull_offers_mark_unaffordable_hulls() -> None:
    campaign = campaign_state()
    campaign.credits = 30
    offers = {offer.hull.id: offer.quote for offer in hull_offers(campaign)}
    assert offers["cobra_destroyer"].candidate is not None
    assert offers["emperor_battleship"].reason == "insufficient credits"


def test_repair_quotes() -> None:
    campaign = campaign_state()
    campaign.roster[0].hull_damage = 2
    assert quote_repair_all(campaign).charge == 16
    assert quote_repair_ship(campaign, "ship-2").charge == 0
    campaign.credits = 0
    assert quote_repair_all(campaign).reason == "insufficient credits"


def test_autosave_reports_failure(tmp_path: Path) -> None:
    campaign = campaign_state()
    assert autosave(campaign, tmp_path / "save.json") is None
    blocked = tmp_path / "file"
    blocked.write_text("x")
    error = autosave(campaign, blocked / "save.json")
    assert error is not None and "UNSAVED" in error
