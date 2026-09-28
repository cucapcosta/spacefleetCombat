"""Interactive New/Continue campaign menu and between-battle interval."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Literal

from spacefleet.campaign.battle import build_battle, close_battle
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
from spacefleet.campaign.models import BattleOutcome, CampaignStatus
from spacefleet.campaign.rules import (
    INITIAL_CREDITS,
    enemy_fleet_for,
    new_campaign,
    validate_campaign_fleet,
    validate_campaign_state,
)
from spacefleet.cli.fitting import FittingChoice, fitting_choices
from spacefleet.cli.fleet_builder_cmd import run_fleet_builder
from spacefleet.cli.terminal_ui import MenuOption, TerminalUI
from spacefleet.commander.upgrade_effects import upgrade_slots_for
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import ShipSpec, fleet_points, ship_points
from spacefleet.persistence.campaign_save import (
    CampaignSaveError,
    default_campaign_path,
    load_campaign,
    save_campaign,
)
from spacefleet.tui.battle_app import TuiBattleRunner

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.campaign.models import CampaignShip, CampaignState
    from spacefleet.tui.runner import BattleRunner

_FittingKind = Literal["weapon", "upgrade", "doctrine"]


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
    ability_names = [
        ability_definition.name
        for ability_id in campaign.commander.active_ability_ids
        if (ability_definition := SkillRegistry.get_active(ability_id)) is not None
    ]
    passive_names = [
        passive_definition.name
        for passive_id in campaign.commander.passive_skill_ids
        if (passive_definition := SkillRegistry.get_passive(passive_id)) is not None
    ]
    rows = [
        f"Encounter: {campaign.encounter}/5",
        f"Credits: {campaign.credits}",
        (
            f"Commander: {campaign.commander.name} — level {campaign.commander.level}, "
            f"XP {campaign.commander.xp}"
        ),
        f"  abilities: {', '.join(ability_names) or '(none)'}",
        f"  passives: {', '.join(passive_names) or '(none)'}",
        "Roster:",
    ]
    if not campaign.roster:
        rows.append("  (empty)")
    for index, ship in enumerate(campaign.roster):
        hull = HullRegistry.get(ship.spec.hull_id)
        role = "flagship" if ship.id == campaign.flagship_id else "ship"
        rows.append(
            f"  {index + 1}. {ship.spec.name} — {hull.name} — {role}, "
            f"damage {ship.hull_damage}, survived {ship.battles_survived}"
        )
        slots = {slot.id: slot for slot in hull.weapon_slots}
        weapons = []
        for slot_id, weapon_id in sorted(ship.spec.weapons.items()):
            slot = slots.get(slot_id)
            slot_name = slot.name if slot is not None else f"Weapon position {slot_id}"
            weapon = WeaponRegistry.get_or_none(weapon_id)
            weapons.append(f"{slot_name}: {weapon.name if weapon is not None else 'Unknown'}")
        rows.append(f"    weapons: {', '.join(weapons) or '(none)'}")
        upgrades = [UpgradeRegistry.get(upgrade_id).name for upgrade_id in ship.spec.upgrade_ids]
        rows.append(f"    upgrades: {', '.join(upgrades) or '(none)'}")
        doctrine = DoctrineRegistry.get_or_none(ship.spec.doctrine_id)
        rows.append(f"    doctrine: {doctrine.name if doctrine is not None else '(none)'}")
    if campaign.flagship_id is None:
        rows.append("Flagship: none — choose one before battle.")
    if campaign.status is CampaignStatus.ACTIVE:
        enemy = enemy_fleet_for(campaign.faction, campaign.encounter)
        rows.append(
            f"Next enemy: {enemy.name} — {len(enemy.ships)} ships, {fleet_points(enemy)} points"
        )
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
    controller_factory: Callable[[BattleSession], BattleRunner] | None,
    output_fn: Callable[[str], None],
    ui: TerminalUI | None = None,
) -> tuple[CampaignState, bool]:
    ship_names = {ship.id: ship.spec.name for ship in campaign.roster}
    try:
        validate_campaign_state(campaign, require_battle_ready=True)
        session = build_battle(campaign)
        controller = (
            TuiBattleRunner(session, ui=ui)
            if controller_factory is None
            else controller_factory(session)
        )
        outcome = controller.run()
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
    ui: TerminalUI,
    controller_factory: Callable[[BattleSession], BattleRunner] | None,
) -> None:
    while True:
        battle_reason = None
        if campaign.status is not CampaignStatus.ACTIVE:
            battle_reason = f"campaign is {campaign.status.value}"
        action = ui.choose(
            "Campaign interval",
            [
                MenuOption("battle", "Start battle", disabled_reason=battle_reason),
                MenuOption("manage", "Manage ships", disabled_reason=battle_reason),
                MenuOption("buy", "Buy hull", disabled_reason=battle_reason),
                MenuOption("repair", "Repair ships", disabled_reason=battle_reason),
                MenuOption("save", "Save"),
                MenuOption("back", "Back"),
            ],
            context=_status(campaign),
        )
        if action is None or action == "back":
            return
        if battle_reason is not None and action in {"battle", "manage", "buy", "repair"}:
            ui.show(battle_reason)
            continue
        if action == "save":
            _autosave(campaign, path, ui.show, explicit=True)
        elif action == "battle":
            campaign, terminal = _battle(campaign, path, controller_factory, ui.show, ui)
            if terminal:
                return
        elif action == "buy":
            campaign = _buy_hull(campaign, path, ui)
        elif action == "repair":
            campaign = _repair_menu(campaign, path, ui)
        elif action == "manage":
            campaign = _manage_campaign(campaign, path, ui)


def _preview_text(before: CampaignState, after: CampaignState) -> str:
    return f"{_credit_preview(before, after)}; resulting credits {after.credits}"


def _campaign_ship_context(campaign: CampaignState, ship_id: str) -> str:
    ship = _ship(campaign, ship_id)
    hull = HullRegistry.get(ship.spec.hull_id)
    rows = [
        f"Credits: {campaign.credits}",
        f"{ship.spec.name} — {hull.name}",
        f"Damage: {ship.hull_damage} | survived: {ship.battles_survived}",
    ]
    for slot in hull.weapon_slots:
        weapon_id = ship.spec.weapons.get(slot.id)
        weapon = WeaponRegistry.get_or_none(weapon_id) if weapon_id is not None else None
        rows.append(
            f"Weapon {slot.id}: {slot.name} | {slot.arc.value} | {slot.size.value} | "
            f"{weapon.name if weapon else 'Empty'}"
        )
    slots = upgrade_slots_for(hull, ship.spec.doctrine_id)
    for position in range(slots):
        upgrade = (
            UpgradeRegistry.get_or_none(ship.spec.upgrade_ids[position])
            if position < len(ship.spec.upgrade_ids)
            else None
        )
        rows.append(f"Upgrade position {position + 1}: {upgrade.name if upgrade else 'Empty'}")
    doctrine = DoctrineRegistry.get_or_none(ship.spec.doctrine_id)
    rows.append(f"Doctrine: {doctrine.name if doctrine else 'None'}")
    return "\n".join(rows)


def _campaign_weapon_name(spec: ShipSpec, slot_id: int) -> str:
    if slot_id not in spec.weapons:
        return "Empty"
    return WeaponRegistry.get(spec.weapons[slot_id]).name


def _unique_probe_name(campaign: CampaignState, base: str) -> str:
    names = {ship.spec.name for ship in campaign.roster}
    name = base
    suffix = 2
    while name in names:
        name = f"{base} {suffix}"
        suffix += 1
    return name


def _buy_hull(campaign: CampaignState, path: Path, ui: TerminalUI) -> CampaignState:
    options: list[MenuOption] = []
    for hull in HullRegistry.by_faction(campaign.faction):
        spec = ShipSpec(_unique_probe_name(campaign, hull.name), hull.id)
        candidate = deepcopy(campaign)
        reason = None
        try:
            buy_ship(candidate, spec)
        except CampaignEconomyError as exc:
            if str(exc) != "insufficient credits":
                continue
            funded = deepcopy(campaign)
            funding = ship_points(spec)
            funded.credits += funding
            funded_start = funded.credits
            buy_ship(funded, spec)
            candidate = funded
            charge = funded_start - funded.credits
            candidate.credits = campaign.credits - charge
            reason = "insufficient credits"
        details = f"{hull.hull_cost} credits | {_preview_text(campaign, candidate)}"
        options.append(MenuOption(hull.id, hull.name, details, reason))
    selected = ui.choose("Buy hull", options, context=f"Credits: {campaign.credits}")
    if selected is None:
        return campaign
    option = next(item for item in options if item.value == selected)
    if option.disabled_reason:
        ui.show(option.disabled_reason)
        return campaign
    hull = HullRegistry.get(selected)
    name = ui.text("Ship name", "campaign.ship_name", hull.name)
    if name is None:
        return campaign
    candidate = deepcopy(campaign)
    try:
        buy_ship(candidate, ShipSpec(name, selected))
    except CampaignEconomyError as exc:
        ui.show(str(exc))
        return campaign
    preview = _preview_text(campaign, candidate)
    if not ui.confirm(f"Buy {name}? {preview}"):
        return campaign
    _autosave(candidate, path, ui.show)
    return candidate


def _repair_menu(campaign: CampaignState, path: Path, ui: TerminalUI) -> CampaignState:
    options: list[MenuOption] = []
    candidates: dict[str, CampaignState] = {}
    operations: list[tuple[str, str, Callable[[CampaignState], int]]] = [
        ("all", "Repair all ships", repair_all),
    ]

    def repair_one(ship_id: str) -> Callable[[CampaignState], int]:
        def operation(state: CampaignState) -> int:
            return repair_ship(state, ship_id)

        return operation

    operations.extend(
        (
            ship.id,
            f"{ship.spec.name} — damage {ship.hull_damage}",
            repair_one(ship.id),
        )
        for ship in campaign.roster
    )
    funding = sum(ship.hull_damage for ship in campaign.roster) * REPAIR_COST_PER_HULL
    for value, label, operation in operations:
        candidate = deepcopy(campaign)
        reason = None
        try:
            operation(candidate)
        except CampaignEconomyError as exc:
            if str(exc) != "insufficient credits":
                continue
            funded = deepcopy(campaign)
            funded.credits += funding
            charge = operation(funded)
            funded.credits = campaign.credits - charge
            candidate = funded
            reason = "insufficient credits"
        options.append(MenuOption(value, label, _preview_text(campaign, candidate), reason))
        if reason is None:
            candidates[value] = candidate
    selected = ui.choose("Repair ships", options, context=f"Credits: {campaign.credits}")
    if selected is None:
        return campaign
    option = next(item for item in options if item.value == selected)
    if option.disabled_reason:
        ui.show(option.disabled_reason)
        return campaign
    candidate = candidates[selected]
    if not ui.confirm(f"{option.label}? {option.details}"):
        return campaign
    _autosave(candidate, path, ui.show)
    return candidate


def _manage_campaign(campaign: CampaignState, path: Path, ui: TerminalUI) -> CampaignState:
    while True:
        options = [
            MenuOption(
                ship.id,
                f"{index + 1}. {ship.spec.name} — {HullRegistry.get(ship.spec.hull_id).name}",
                f"damage {ship.hull_damage} | survived {ship.battles_survived}",
            )
            for index, ship in enumerate(campaign.roster)
        ]
        options.append(MenuOption("back", "Back"))
        selected = ui.choose("Manage ships", options, context=_status(campaign))
        if selected is None or selected == "back":
            return campaign
        campaign = _manage_ship(campaign, selected, path, ui)


def _manage_ship(
    campaign: CampaignState,
    ship_id: str,
    path: Path,
    ui: TerminalUI,
) -> CampaignState:
    while any(ship.id == ship_id for ship in campaign.roster):
        ship = _ship(campaign, ship_id)
        hull = HullRegistry.get(ship.spec.hull_id)
        options = [
            MenuOption(
                f"weapon:{slot.id}",
                f"Weapon: {slot.name}",
                f"{slot.arc.value} arc | {slot.size.value} | "
                f"{_campaign_weapon_name(ship.spec, slot.id)}",
            )
            for slot in hull.weapon_slots
        ]
        for position in range(upgrade_slots_for(hull, ship.spec.doctrine_id)):
            current = (
                UpgradeRegistry.get(ship.spec.upgrade_ids[position]).name
                if position < len(ship.spec.upgrade_ids)
                else "Empty"
            )
            options.append(
                MenuOption(
                    f"upgrade:{position}",
                    f"Upgrade position {position + 1}: {current}",
                )
            )
        doctrine = DoctrineRegistry.get_or_none(ship.spec.doctrine_id)
        options.extend(
            (
                MenuOption("doctrine", f"Doctrine: {doctrine.name if doctrine else 'None'}"),
                MenuOption("flagship", "Make flagship"),
                MenuOption("discard", "Discard ship"),
                MenuOption("back", "Back"),
            )
        )
        action = ui.choose(
            "Manage ship",
            options,
            context=_campaign_ship_context(campaign, ship_id),
        )
        if action is None or action == "back":
            return campaign
        if action.startswith("weapon:"):
            campaign = _campaign_fitting(
                campaign, ship_id, path, ui, "weapon", int(action.partition(":")[2])
            )
        elif action.startswith("upgrade:"):
            position = int(action.partition(":")[2])
            slot_id = position if position < len(ship.spec.upgrade_ids) else None
            campaign = _campaign_fitting(campaign, ship_id, path, ui, "upgrade", slot_id)
        elif action == "doctrine":
            campaign = _campaign_fitting(campaign, ship_id, path, ui, "doctrine", None)
        elif action == "flagship":
            candidate = deepcopy(campaign)
            try:
                set_flagship(candidate, ship_id)
            except CampaignEconomyError as exc:
                ui.show(str(exc))
                continue
            if ui.confirm(f"Make {ship.spec.name} the flagship?"):
                campaign = candidate
                _autosave(campaign, path, ui.show)
        elif action == "discard":
            candidate = deepcopy(campaign)
            try:
                discard_ship(candidate, ship_id)
            except CampaignEconomyError as exc:
                ui.show(str(exc))
                continue
            if ui.confirm(f"Discard {ship.spec.name} permanently with no refund?"):
                _autosave(candidate, path, ui.show)
                return candidate
    return campaign


def _refit_preview(charge: int, resulting_credits: int) -> str:
    if charge > 0:
        change = f"charge {charge} credits"
    elif charge < 0:
        change = f"refund {-charge} credits"
    else:
        change = "no credit change"
    return f"{change}; resulting credits {resulting_credits}"


def _quote_refit(
    campaign: CampaignState,
    ship_id: str,
    replacement: ShipSpec,
) -> tuple[CampaignState | None, int, int, str | None]:
    candidate = deepcopy(campaign)
    try:
        charge = reequip_ship(candidate, ship_id, replacement)
    except CampaignEconomyError as exc:
        if str(exc) != "insufficient credits":
            raise
        funded = deepcopy(campaign)
        funded.credits += ship_points(replacement)
        charge = reequip_ship(funded, ship_id, replacement)
        return None, charge, campaign.credits - charge, "insufficient credits"
    return candidate, charge, candidate.credits, None


def _campaign_fitting(
    campaign: CampaignState,
    ship_id: str,
    path: Path,
    ui: TerminalUI,
    kind: _FittingKind,
    slot_id: int | None,
) -> CampaignState:
    ship = _ship(campaign, ship_id)

    def validate_replacement(replacement: ShipSpec) -> None:
        funded = deepcopy(campaign)
        funded.credits += ship_points(replacement)
        reequip_ship(funded, ship_id, replacement)

    choices = fitting_choices(
        ship.spec,
        campaign.faction,
        kind=kind,
        slot_id=slot_id,
        is_flagship=(ship_id == campaign.flagship_id),
        candidate_validator=validate_replacement,
    )
    options: list[MenuOption] = []
    candidates: dict[str, CampaignState] = {}
    replacements: list[FittingChoice] = list(choices)
    removed = deepcopy(ship.spec)
    if kind == "weapon" and slot_id is not None and slot_id in removed.weapons:
        removed.weapons.pop(slot_id)
        replacements.insert(0, FittingChoice("remove", "Remove", "", removed))
    elif kind == "upgrade" and slot_id is not None:
        removed.upgrade_ids.pop(slot_id)
        replacements.insert(0, FittingChoice("remove", "Remove", "", removed))
    elif kind == "doctrine" and removed.doctrine_id is not None:
        removed.doctrine_id = None
        replacements.insert(0, FittingChoice("remove", "Remove", "", removed))
    for choice in replacements:
        try:
            candidate, charge, balance, reason = _quote_refit(campaign, ship_id, choice.replacement)
        except CampaignEconomyError:
            continue
        preview = _refit_preview(charge, balance)
        details = f"{choice.details}\n{preview}" if choice.details else preview
        options.append(MenuOption(choice.value, choice.label, details, reason))
        if candidate is not None:
            candidates[choice.value] = candidate
    selected = ui.choose(
        f"Choose {kind}",
        options,
        context=_campaign_ship_context(campaign, ship_id),
    )
    if selected is None:
        return campaign
    option = next(item for item in options if item.value == selected)
    if option.disabled_reason:
        ui.show(option.disabled_reason)
        return campaign
    candidate = candidates[selected]
    if not ui.confirm(f"Apply {option.label}? {option.details}"):
        return campaign
    _autosave(candidate, path, ui.show)
    return candidate


def _new_campaign(path: Path, ui: TerminalUI) -> CampaignState | None:
    if path.exists() and not ui.confirm("Replace the existing campaign save?"):
        return None
    faction_raw = ui.choose(
        "Campaign faction",
        [MenuOption(faction.value, faction.value.replace("_", " ").title()) for faction in Faction],
    )
    if faction_raw is None:
        return None
    name = ui.text("Commander name", "campaign.name")
    if name is None or not name:
        return None
    seed_raw = ui.text("Campaign seed", "campaign.seed", "")
    if seed_raw is None:
        return None
    try:
        seed = None if not seed_raw else int(seed_raw)
        if seed is not None and seed < 0:
            raise ValueError
    except ValueError:
        ui.show("Seed must be a non-negative integer.")
        return None
    fleet = run_fleet_builder(
        faction=Faction(faction_raw),
        budget=INITIAL_CREDITS,
        name=name,
        ui=ui,
        candidate_validator=validate_campaign_fleet,
    )
    if fleet is None:
        ui.show("Fleet building cancelled; existing save unchanged.")
        return None
    try:
        campaign = new_campaign(fleet, name, seed)
    except ValueError as exc:
        ui.show(f"Campaign cannot start: {exc}")
        return None
    _autosave(campaign, path, ui.show, explicit=True)
    return campaign


def run_campaign_menu(
    *,
    save_path: Path | None = None,
    ui: TerminalUI | None = None,
    controller_factory: Callable[[BattleSession], BattleRunner] | None = None,
) -> None:
    """Run the menu-driven New/Continue campaign session."""
    ui = ui or TerminalUI()
    path = save_path if save_path is not None else default_campaign_path()
    while True:
        choice = ui.choose(
            "Campaign",
            [
                MenuOption("new", "New campaign"),
                MenuOption("continue", "Continue campaign"),
                MenuOption("back", "Back"),
            ],
        )
        if choice is None or choice == "back":
            return
        if choice == "new":
            campaign = _new_campaign(path, ui)
            if campaign is not None:
                _interval(campaign, path, ui, controller_factory)
                return
        elif choice == "continue":
            if not path.is_file():
                ui.show("No saved campaign exists.")
                continue
            try:
                campaign = load_campaign(path)
            except (CampaignSaveError, UnicodeError) as exc:
                ui.show(f"Could not continue campaign: {exc}")
                continue
            _interval(campaign, path, ui, controller_factory)
            return
