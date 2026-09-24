"""Interactive New/Continue campaign menu and between-battle interval."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from spacefleet.campaign.battle import build_battle, close_battle
from spacefleet.campaign.economy import (
    buy_ship,
    discard_ship,
    reequip_ship,
    repair_all,
    repair_ship,
    set_flagship,
)
from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.campaign.rules import (
    BLOCKED_UPGRADES,
    INITIAL_CREDITS,
    SUPPORTED_WEAPON_TYPES,
    enemy_fleet_for,
    new_campaign,
    validate_campaign_state,
)
from spacefleet.cli.fleet_builder_cmd import run_fleet_builder
from spacefleet.cli.local_battle import LocalBattleController
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import ShipSpec, fleet_points
from spacefleet.persistence.campaign_save import (
    CampaignSaveError,
    default_campaign_path,
    load_campaign,
    save_campaign,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.campaign.models import CampaignShip, CampaignState


_MENU = "Campaign: new | continue | back"
_HELP = """\
Interval commands:
  status | catalog | help | save | battle | back
  buy <hull-id> <name...>
  equip <ship-id> weapon <slot> <weapon-id>
  equip <ship-id> upgrade <upgrade-id>
  equip <ship-id> doctrine <doctrine-id>
  remove <ship-id> weapon <slot>
  remove <ship-id> upgrade <upgrade-id>
  remove <ship-id> doctrine
  repair <ship-id|all> | discard <ship-id> | flagship <ship-id>
Buy adds only the hull; equip weapons afterwards using the stable ship ID.
Ship IDs shown by status are stable across battles and roster edits.
Mutating store commands require a separate 'confirm'.
"""


def _read(input_fn: Callable[[str], str], prompt: str) -> str | None:
    try:
        return input_fn(prompt).strip()
    except (EOFError, KeyboardInterrupt, StopIteration):
        return None


def _confirmed(input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> bool:
    answer = _read(input_fn, "  Type 'confirm' to proceed: ")
    if answer is not None and answer.lower() == "confirm":
        return True
    output_fn("  Cancelled; campaign unchanged.")
    return False


def _autosave(
    campaign: CampaignState,
    path: Path,
    output_fn: Callable[[str], None],
    *,
    explicit: bool = False,
) -> bool:
    try:
        save_campaign(campaign, path)
    except CampaignSaveError as exc:
        output_fn(f"  Change kept in memory but UNSAVED: {exc}. Use 'save' to retry.")
        return False
    if explicit:
        output_fn(f"  Campaign saved to {path}.")
    return True


def _status(campaign: CampaignState) -> str:
    rows = [
        f"Encounter: {campaign.encounter}/5",
        f"Credits: {campaign.credits}",
        (
            f"Commander: {campaign.commander.name} — level {campaign.commander.level}, "
            f"XP {campaign.commander.xp}"
        ),
        f"  abilities: {', '.join(campaign.commander.active_ability_ids) or '(none)'}",
        f"  passives: {', '.join(campaign.commander.passive_skill_ids) or '(none)'}",
        "Roster:",
    ]
    if not campaign.roster:
        rows.append("  (empty)")
    for ship in campaign.roster:
        role = "flagship" if ship.id == campaign.flagship_id else "ship"
        rows.append(
            f"  {ship.id}: {ship.spec.name} ({ship.spec.hull_id}) — {role}, "
            f"damage {ship.hull_damage}, survived {ship.battles_survived}"
        )
        weapons = ", ".join(
            f"{slot}={weapon_id}" for slot, weapon_id in sorted(ship.spec.weapons.items())
        )
        rows.append(f"    weapons: {weapons or '(none)'}")
        rows.append(f"    upgrades: {', '.join(ship.spec.upgrade_ids) or '(none)'}")
        rows.append(f"    doctrine: {ship.spec.doctrine_id or '(none)'}")
    if campaign.flagship_id is None:
        rows.append("Flagship: none — choose one before battle.")
    if campaign.status is CampaignStatus.ACTIVE:
        enemy = enemy_fleet_for(campaign.faction, campaign.encounter)
        rows.append(
            f"Next enemy: {enemy.name} — {len(enemy.ships)} ships, {fleet_points(enemy)} points"
        )
    return "\n".join(rows)


def _catalog(campaign: CampaignState) -> str:
    rows = ["Hulls (hull only; equip weapons separately after purchase):"]
    for hull in HullRegistry.by_faction(campaign.faction):
        rows.append(f"  {hull.id}: {hull.hull_cost} credits")
    rows.append("Weapons:")
    for weapon in WeaponRegistry.all().values():
        note = "" if weapon.weapon_type in SUPPORTED_WEAPON_TYPES else " — UNSUPPORTED mechanic"
        rows.append(f"  {weapon.id}: {weapon.cost} credits{note}")
    rows.append("Upgrades:")
    for upgrade in UpgradeRegistry.all().values():
        note = " — UNSUPPORTED mechanic" if upgrade.id in BLOCKED_UPGRADES else ""
        rows.append(f"  {upgrade.id}: {upgrade.cost} credits{note}")
    rows.append("Doctrines:")
    for doctrine in DoctrineRegistry.for_faction(campaign.faction):
        rows.append(f"  {doctrine.id}: {doctrine.cost} credits")
    return "\n".join(rows)


def _ship(campaign: CampaignState, ship_id: str) -> CampaignShip:
    for ship in campaign.roster:
        if ship.id == ship_id:
            return ship
    raise ValueError(f"unknown campaign ship {ship_id!r}")


def _credit_preview(before: CampaignState, after: CampaignState) -> str:
    charge = before.credits - after.credits
    if charge > 0:
        return f"charge {charge} credits"
    if charge < 0:
        return f"refund {-charge} credits"
    return "no credit change"


def _refit_candidate(campaign: CampaignState, args: list[str], *, remove: bool) -> CampaignState:
    if len(args) < 2:
        raise ValueError("usage: equip/remove <ship-id> <weapon|upgrade|doctrine> ...")
    ship_id, kind = args[0], args[1].lower()
    candidate = deepcopy(campaign)
    replacement = deepcopy(_ship(candidate, ship_id).spec)
    values = args[2:]
    if kind == "weapon" and ((remove and len(values) == 1) or (not remove and len(values) == 2)):
        try:
            slot = int(values[0])
        except ValueError as exc:
            raise ValueError("weapon slot must be an integer") from exc
        if remove:
            if slot not in replacement.weapons:
                raise ValueError(f"weapon slot {slot} is already empty")
            replacement.weapons.pop(slot)
        else:
            replacement.weapons[slot] = values[1]
    elif kind == "upgrade" and len(values) == 1:
        if remove:
            if values[0] not in replacement.upgrade_ids:
                raise ValueError(f"upgrade {values[0]!r} is not installed")
            replacement.upgrade_ids.remove(values[0])
        else:
            replacement.upgrade_ids.append(values[0])
    elif kind == "doctrine" and ((remove and not values) or (not remove and len(values) == 1)):
        if remove:
            if replacement.doctrine_id is None:
                raise ValueError("ship has no doctrine")
            replacement.doctrine_id = None
        else:
            replacement.doctrine_id = values[0]
    else:
        raise ValueError("usage: equip/remove <ship-id> <weapon|upgrade|doctrine> ...")
    reequip_ship(candidate, ship_id, replacement)
    return candidate


def _store_candidate(campaign: CampaignState, parts: list[str]) -> tuple[CampaignState, str]:
    cmd, args = parts[0], parts[1:]
    candidate = deepcopy(campaign)
    if cmd == "buy" and len(args) >= 2:
        spec = ShipSpec(name=" ".join(args[1:]), hull_id=args[0])
        ship_id = buy_ship(candidate, spec)
        return candidate, f"Buy {ship_id} {spec.name}: {_credit_preview(campaign, candidate)}."
    if cmd == "equip":
        candidate = _refit_candidate(campaign, args, remove=False)
        return candidate, f"Apply refit: {_credit_preview(campaign, candidate)}."
    if cmd == "remove":
        candidate = _refit_candidate(campaign, args, remove=True)
        return candidate, f"Remove equipment: {_credit_preview(campaign, candidate)}."
    if cmd == "discard" and len(args) == 1:
        saved = _ship(candidate, args[0])
        discard_ship(candidate, args[0])
        return candidate, f"Discard {saved.id} {saved.spec.name}: permanent loss, no refund."
    if cmd == "repair" and len(args) == 1:
        if args[0].lower() == "all":
            repair_all(candidate)
            label = "Repair all ships"
        else:
            repair_ship(candidate, args[0])
            label = f"Repair {args[0]}"
        return candidate, f"{label}: {_credit_preview(campaign, candidate)}."
    if cmd == "flagship" and len(args) == 1:
        set_flagship(candidate, args[0])
        return candidate, f"Set {args[0]} as flagship: no credit change."
    raise ValueError("unknown or malformed store command; type 'help'")


def _battle(
    campaign: CampaignState,
    path: Path,
    controller_factory: Callable[[BattleSession], LocalBattleController],
    output_fn: Callable[[str], None],
) -> tuple[CampaignState, bool]:
    ship_names = {ship.id: ship.spec.name for ship in campaign.roster}
    try:
        validate_campaign_state(campaign, require_battle_ready=True)
        session = build_battle(campaign)
        outcome = controller_factory(session).run()
    except ValueError as exc:
        output_fn(f"  Battle cannot start: {exc}")
        return campaign, False
    if outcome is BattleOutcome.ABANDONED:
        output_fn("  Battle abandoned; campaign interval unchanged and not saved.")
        return campaign, False
    try:
        report = close_battle(campaign, session, outcome)
    except ValueError as exc:
        output_fn(f"  Battle could not close: {exc}")
        return campaign, False
    casualty_details = ", ".join(
        f"{ship_id} ({ship_names[ship_id]})" for ship_id in report.casualties
    )
    output_fn(
        f"  Battle {report.outcome.value.replace('_', ' ')}: "
        f"{report.enemy_destroyed} enemies destroyed, {report.player_survivors} survivors, "
        f"credits awarded {report.credits_awarded}, "
        f"casualties: {casualty_details or '(none)'}."
    )
    output_fn(_status(campaign))
    saved = _autosave(campaign, path, output_fn)
    if campaign.status is CampaignStatus.COMPLETED:
        output_fn("  Campaign completed after five victories.")
        return campaign, saved
    if campaign.status is CampaignStatus.DEFEATED:
        output_fn(f"  Campaign defeated ({report.outcome.value.replace('_', ' ')}).")
        return campaign, saved
    return campaign, False


def _interval(
    campaign: CampaignState,
    path: Path,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    controller_factory: Callable[[BattleSession], LocalBattleController],
) -> None:
    if campaign.status is not CampaignStatus.ACTIVE:
        output_fn(f"  Campaign is {campaign.status.value}; no further battles can start.")
        return
    output_fn(_status(campaign))
    while True:
        raw = _read(input_fn, "  campaign> ")
        if raw is None or raw.lower() in {"back", "quit", "exit"}:
            return
        parts = raw.split()
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd == "status":
            output_fn(_status(campaign))
        elif cmd == "help":
            output_fn(_HELP)
        elif cmd == "catalog":
            output_fn(_catalog(campaign))
        elif cmd == "save":
            _autosave(campaign, path, output_fn, explicit=True)
        elif cmd == "battle":
            campaign, terminal = _battle(campaign, path, controller_factory, output_fn)
            if terminal:
                return
        elif cmd in {"buy", "equip", "remove", "discard", "repair", "flagship"}:
            try:
                candidate, preview = _store_candidate(campaign, [cmd, *parts[1:]])
            except ValueError as exc:
                output_fn(f"  Store rejected: {exc}")
                continue
            output_fn(f"  {preview}")
            if _confirmed(input_fn, output_fn):
                campaign = candidate
                _autosave(campaign, path, output_fn)
        else:
            output_fn("  Unknown command; type 'help'.")


def _new_campaign(
    path: Path,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> CampaignState | None:
    if path.exists():
        output_fn("  A saved campaign exists. Replacing it will erase that campaign.")
        if not _confirmed(input_fn, output_fn):
            return None
    faction_raw = _read(input_fn, "  Faction (imperial_navy / chaos_fleet): ")
    if faction_raw is None or faction_raw.lower() in {"cancel", "back"}:
        return None
    try:
        faction = Faction(faction_raw.lower())
    except ValueError:
        output_fn(f"  Unknown faction {faction_raw!r}.")
        return None
    name = _read(input_fn, "  Fleet and commander name: ")
    if name is None or name.lower() in {"cancel", "back"} or not name:
        return None
    seed_raw = _read(input_fn, "  Campaign seed (blank for random, cancel to stop): ")
    if seed_raw is None or seed_raw.lower() in {"cancel", "back"}:
        return None
    try:
        seed = None if not seed_raw else int(seed_raw)
        if seed is not None and seed < 0:
            raise ValueError
    except ValueError:
        output_fn("  Seed must be a non-negative integer.")
        return None
    fleet = run_fleet_builder(faction=faction, budget=INITIAL_CREDITS, name=name)
    if fleet is None:
        output_fn("  Fleet building cancelled; existing save unchanged.")
        return None
    try:
        campaign = new_campaign(fleet, name, seed)
    except ValueError as exc:
        output_fn(f"  Campaign cannot start: {exc}")
        return None
    _autosave(campaign, path, output_fn, explicit=True)
    return campaign


def run_campaign_menu(
    *,
    save_path: Path | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    controller_factory: Callable[[BattleSession], LocalBattleController] = LocalBattleController,
) -> None:
    """Run one New/Continue campaign session."""
    path = save_path if save_path is not None else default_campaign_path()
    while True:
        output_fn(_MENU)
        raw = _read(input_fn, "  campaign menu> ")
        if raw is None or raw.lower() in {"back", "quit", "exit"}:
            return
        choice = raw.lower()
        if choice in {"new", "1"}:
            campaign = _new_campaign(path, input_fn, output_fn)
            if campaign is not None:
                _interval(campaign, path, input_fn, output_fn, controller_factory)
                return
        elif choice in {"continue", "2"}:
            if not path.is_file():
                output_fn("  No saved campaign exists.")
                continue
            try:
                campaign = load_campaign(path)
            except CampaignSaveError as exc:
                output_fn(f"  Could not continue campaign: {exc}")
                continue
            _interval(campaign, path, input_fn, output_fn, controller_factory)
            return
        else:
            output_fn("  Choose new, continue, or back.")
