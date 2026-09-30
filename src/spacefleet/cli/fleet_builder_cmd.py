"""Interactive fleet builder — menu wrapper around ``FleetBuilderSession``.

``FleetBuilderSession`` lives in :mod:`spacefleet.tui.model.fleet_builder` and is
re-exported here.  ``run_fleet_builder`` is the thin I/O loop the app menu calls.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from spacefleet.cli.fitting import FittingChoice, fitting_choices
from spacefleet.cli.terminal_ui import MenuOption, TerminalUI
from spacefleet.commander.upgrade_effects import upgrade_slots_for
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    ShipSpec,
    fleet_points,
    ship_points,
    validate_fleet_spec,
)
from spacefleet.persistence.fleet_save import default_fleet_dir, load_fleet, save_fleet
from spacefleet.tui.model.fleet_builder import FleetBuilderSession as FleetBuilderSession

if TYPE_CHECKING:
    from collections.abc import Callable

_FittingKind = Literal["weapon", "upgrade", "doctrine"]


def run_fleet_builder(
    *,
    faction: Faction | None = None,
    budget: int | None = None,
    name: str | None = None,
    ui: TerminalUI | None = None,
    candidate_validator: Callable[[FleetSpec], None] | None = None,
) -> FleetSpec | None:
    """Build a fleet with discoverable menus and detached candidate validation."""
    ui = ui or TerminalUI()
    if faction is None:
        selected_faction = ui.choose(
            "Fleet faction",
            [
                MenuOption(member.value, member.value.replace("_", " ").title())
                for member in Faction
            ],
        )
        if selected_faction is None:
            return None
        faction = Faction(selected_faction)
    if budget is None:
        while True:
            raw_budget = ui.text("Points budget", "fleet.budget", "1000")
            if raw_budget is None:
                return None
            try:
                budget = int(raw_budget)
                if not 1 <= budget <= 100_000:
                    raise ValueError
            except ValueError:
                ui.show("Points budget must be between 1 and 100000.")
                continue
            break
    if name is None:
        name = ui.text("Fleet name", "fleet.name", "My Fleet")
        if name is None:
            return None

    session = FleetBuilderSession(faction, budget=budget, name=name)
    while True:
        action = ui.choose(
            "Fleet Builder",
            _roster_options(session),
            context=_roster_context(session),
        )
        if action == "add_ship":
            _add_ship(session, ui, candidate_validator)
        elif action is not None and action.startswith("ship:"):
            _edit_ship(session, int(action.partition(":")[2]), ui, candidate_validator)
        elif action == "save":
            _save_draft(session, ui)
        elif action == "load":
            _load_draft(session, ui, candidate_validator)
        elif action == "done":
            try:
                validate_fleet_spec(session.fleet, budget=budget)
                if candidate_validator is not None:
                    candidate_validator(deepcopy(session.fleet))
            except (FleetSpecError, ValueError) as exc:
                ui.show(str(exc))
                continue
            if ui.confirm("Finish this fleet?"):
                return deepcopy(session.fleet)
        elif (action == "cancel" or action is None) and ui.confirm("Discard this fleet draft?"):
            return None


def _roster_options(session: FleetBuilderSession) -> list[MenuOption]:
    options = [MenuOption("add_ship", "Add ship", "Choose a hull and name the new ship.")]
    for index, ship in enumerate(session.fleet.ships):
        hull = HullRegistry.get(ship.hull_id)
        flag = " [FLAGSHIP]" if index == session.fleet.flagship_index else ""
        options.append(
            MenuOption(
                f"ship:{index}",
                f"{index + 1}. {ship.name} — {hull.name}{flag}",
                _ship_context(session, index),
            )
        )
    options.extend(
        (
            MenuOption("save", "Save fleet"),
            MenuOption("load", "Load fleet"),
            MenuOption("done", "Finish"),
            MenuOption("cancel", "Cancel"),
        )
    )
    return options


def _roster_context(session: FleetBuilderSession) -> str:
    if not session.fleet.ships:
        roster = "No ships in draft."
    else:
        rows = []
        for index, ship in enumerate(session.fleet.ships):
            hull = HullRegistry.get(ship.hull_id)
            flag = " [FLAGSHIP]" if index == session.fleet.flagship_index else ""
            rows.append(f"{index + 1}. {ship.name} — {hull.name} — {ship_points(ship)} pts{flag}")
        roster = "\n".join(rows)
    return (
        f"{session.fleet.name} | {fleet_points(session.fleet)} / {session.budget} pts | "
        f"{session.remaining} remaining\n{roster}"
    )


def _ship_context(session: FleetBuilderSession, index: int) -> str:
    ship = session.fleet.ships[index]
    hull = HullRegistry.get(ship.hull_id)
    rows = [
        f"{session.fleet.name} | {session.remaining} pts remaining",
        f"{ship.name} — {hull.name} — {ship_points(ship)} pts",
    ]
    for slot in hull.weapon_slots:
        weapon_id = ship.weapons.get(slot.id)
        weapon = WeaponRegistry.get_or_none(weapon_id) if weapon_id is not None else None
        fitted = weapon.name if weapon is not None else "Empty"
        rows.append(
            f"Weapon {slot.id}: {slot.name} | {slot.arc.value} | {slot.size.value} | {fitted}"
        )
    slots = upgrade_slots_for(hull, ship.doctrine_id)
    for position in range(slots):
        upgrade = (
            UpgradeRegistry.get_or_none(ship.upgrade_ids[position])
            if position < len(ship.upgrade_ids)
            else None
        )
        rows.append(f"Upgrade position {position + 1}: {upgrade.name if upgrade else 'Empty'}")
    doctrine = DoctrineRegistry.get_or_none(ship.doctrine_id)
    rows.append(f"Doctrine: {doctrine.name if doctrine else 'None'}")
    return "\n".join(rows)


def _fitted_weapon_name(ship: ShipSpec, slot_id: int) -> str:
    if slot_id not in ship.weapons:
        return "Empty"
    return WeaponRegistry.get(ship.weapons[slot_id]).name


def _add_ship(
    session: FleetBuilderSession,
    ui: TerminalUI,
    candidate_validator: Callable[[FleetSpec], None] | None,
) -> None:
    options: list[MenuOption] = []
    used_names = {ship.name for ship in session.fleet.ships}
    for hull in HullRegistry.by_faction(session.fleet.faction):
        probe_name = hull.name
        suffix = 2
        while probe_name in used_names:
            probe_name = f"{hull.name} {suffix}"
            suffix += 1
        candidate = deepcopy(session.fleet)
        candidate.ships.append(ShipSpec(name=probe_name, hull_id=hull.id))
        try:
            _validate_candidate(candidate, None, candidate_validator)
        except (FleetSpecError, ValueError):
            continue
        reason = None
        if hull.hull_cost > session.remaining:
            reason = f"needs {hull.hull_cost} pts; {session.remaining} remaining"
        details = (
            f"{hull.hull_cost} pts | {hull.classification.value} | speed {hull.speed:g} | "
            f"hull {hull.hull_hits} | shields {hull.shields} | "
            f"{len(hull.weapon_slots)} weapon slots"
        )
        options.append(MenuOption(hull.id, hull.name, details, reason))
    hull_id = ui.choose("Add ship", options, context=f"{session.remaining} pts remaining")
    if hull_id is None:
        return
    selected_hull = next(option for option in options if option.value == hull_id)
    if selected_hull.disabled_reason is not None:
        ui.show(selected_hull.disabled_reason)
        return
    hull = HullRegistry.get(hull_id)
    ship_name = ui.text("Ship name", "fleet.ship_name", hull.name)
    if ship_name is None:
        return
    candidate = deepcopy(session.fleet)
    candidate.ships.append(ShipSpec(name=ship_name, hull_id=hull_id))
    try:
        _validate_candidate(candidate, session.budget, candidate_validator)
    except (FleetSpecError, ValueError) as exc:
        ui.show(str(exc))
        return
    session.fleet = candidate


def _edit_ship(
    session: FleetBuilderSession,
    index: int,
    ui: TerminalUI,
    candidate_validator: Callable[[FleetSpec], None] | None,
) -> None:
    while 0 <= index < len(session.fleet.ships):
        ship = session.fleet.ships[index]
        hull = HullRegistry.get(ship.hull_id)
        options = [
            MenuOption(
                f"weapon:{slot.id}",
                f"Weapon: {slot.name}",
                f"{slot.arc.value} arc | {slot.size.value} | {_fitted_weapon_name(ship, slot.id)}",
            )
            for slot in hull.weapon_slots
        ]
        for position in range(upgrade_slots_for(hull, ship.doctrine_id)):
            current = (
                UpgradeRegistry.get(ship.upgrade_ids[position]).name
                if position < len(ship.upgrade_ids)
                else "Empty"
            )
            options.append(
                MenuOption(
                    f"upgrade:{position}",
                    f"Upgrade position {position + 1}: {current}",
                )
            )
        doctrine = DoctrineRegistry.get_or_none(ship.doctrine_id)
        options.extend(
            (
                MenuOption("doctrine", f"Doctrine: {doctrine.name if doctrine else 'None'}"),
                MenuOption("flagship", "Make flagship"),
                MenuOption("default", "Apply default loadout"),
                MenuOption("remove_ship", "Remove ship"),
                MenuOption("back", "Back"),
            )
        )
        action = ui.choose("Configure ship", options, context=_ship_context(session, index))
        if action is None or action == "back":
            return
        if action.startswith("weapon:"):
            _choose_fitting(
                session,
                index,
                ui,
                kind="weapon",
                slot_id=int(action.partition(":")[2]),
                candidate_validator=candidate_validator,
            )
        elif action.startswith("upgrade:"):
            position = int(action.partition(":")[2])
            _choose_fitting(
                session,
                index,
                ui,
                kind="upgrade",
                slot_id=position if position < len(ship.upgrade_ids) else None,
                candidate_validator=candidate_validator,
            )
        elif action == "doctrine":
            _choose_fitting(
                session,
                index,
                ui,
                kind="doctrine",
                slot_id=None,
                candidate_validator=candidate_validator,
            )
        elif action == "flagship":
            candidate = deepcopy(session.fleet)
            candidate.flagship_index = index
            if _assign_candidate(session, candidate, ui, candidate_validator):
                return
        elif action == "default":
            from spacefleet.models.fleet_spec import apply_default_loadout

            candidate = deepcopy(session.fleet)
            apply_default_loadout(candidate.ships[index])
            _assign_candidate(session, candidate, ui, candidate_validator)
        elif action == "remove_ship":
            if not ui.confirm(f"Remove {ship.name}?"):
                continue
            candidate = deepcopy(session.fleet)
            candidate.ships.pop(index)
            if index < candidate.flagship_index:
                candidate.flagship_index -= 1
            elif index == candidate.flagship_index or candidate.flagship_index >= len(
                candidate.ships
            ):
                candidate.flagship_index = 0
            if _assign_candidate(session, candidate, ui, candidate_validator):
                return


def _choose_fitting(
    session: FleetBuilderSession,
    index: int,
    ui: TerminalUI,
    *,
    kind: _FittingKind,
    slot_id: int | None,
    candidate_validator: Callable[[FleetSpec], None] | None,
) -> None:
    ship = session.fleet.ships[index]

    def validate_replacement(replacement: ShipSpec) -> None:
        candidate = deepcopy(session.fleet)
        candidate.ships[index] = deepcopy(replacement)
        validate_fleet_spec(candidate)
        if candidate_validator is not None:
            candidate_validator(candidate)

    choices = fitting_choices(
        ship,
        session.fleet.faction,
        kind=kind,
        slot_id=slot_id,
        is_flagship=(index == session.fleet.flagship_index),
        candidate_validator=validate_replacement,
    )
    options: list[MenuOption] = []
    replacements: dict[str, ShipSpec] = {}
    remove = _removed_fitting(ship, kind, slot_id)
    if remove is not None:
        candidate = deepcopy(session.fleet)
        candidate.ships[index] = remove
        try:
            _validate_candidate(candidate, session.budget, candidate_validator)
        except (FleetSpecError, ValueError):
            pass
        else:
            options.append(MenuOption("remove", "Remove"))
            replacements["remove"] = remove
    for choice in choices:
        reason = _affordability_reason(session, index, choice)
        options.append(MenuOption(choice.value, choice.label, choice.details, reason))
        replacements[choice.value] = choice.replacement
    selected = ui.choose(
        f"Choose {kind}",
        options,
        context=_ship_context(session, index),
    )
    if selected is None:
        return
    selected_option = next(option for option in options if option.value == selected)
    if selected_option.disabled_reason is not None:
        ui.show(selected_option.disabled_reason)
        return
    replacement = replacements[selected]
    candidate = deepcopy(session.fleet)
    candidate.ships[index] = deepcopy(replacement)
    session.fleet = candidate


def _removed_fitting(
    spec: ShipSpec,
    kind: _FittingKind,
    slot_id: int | None,
) -> ShipSpec | None:
    replacement = deepcopy(spec)
    if kind == "weapon":
        assert slot_id is not None
        if slot_id not in replacement.weapons:
            return None
        replacement.weapons.pop(slot_id)
    elif kind == "upgrade":
        if slot_id is None:
            return None
        replacement.upgrade_ids.pop(slot_id)
    else:
        if replacement.doctrine_id is None:
            return None
        replacement.doctrine_id = None
    return replacement


def _affordability_reason(
    session: FleetBuilderSession,
    index: int,
    choice: FittingChoice,
) -> str | None:
    total = (
        fleet_points(session.fleet)
        - ship_points(session.fleet.ships[index])
        + ship_points(choice.replacement)
    )
    if total <= session.budget:
        return None
    return f"costs {total} pts; budget is {session.budget}"


def _assign_candidate(
    session: FleetBuilderSession,
    candidate: FleetSpec,
    ui: TerminalUI,
    candidate_validator: Callable[[FleetSpec], None] | None,
) -> bool:
    try:
        _validate_candidate(candidate, session.budget, candidate_validator)
    except (FleetSpecError, ValueError) as exc:
        ui.show(str(exc))
        return False
    session.fleet = candidate
    return True


def _validate_candidate(
    candidate: FleetSpec,
    budget: int | None,
    candidate_validator: Callable[[FleetSpec], None] | None,
) -> None:
    if not candidate.ships:
        return
    validate_fleet_spec(candidate, budget=budget)
    if candidate_validator is not None:
        candidate_validator(candidate)


def _save_draft(session: FleetBuilderSession, ui: TerminalUI) -> None:
    safe = session.fleet.name.lower().replace(" ", "_")
    default_path = default_fleet_dir() / f"{safe}.json"
    raw_path = ui.text("Save path", "fleet.path", str(default_path))
    if raw_path is None:
        return
    path = Path(raw_path)
    if path.exists() and not ui.confirm(f"Replace {path}?"):
        return
    try:
        written = save_fleet(session.fleet, path)
    except OSError as exc:
        ui.show(f"save failed: {exc}")
        return
    ui.show(f"Saved to {written}")


def _load_draft(
    session: FleetBuilderSession,
    ui: TerminalUI,
    candidate_validator: Callable[[FleetSpec], None] | None,
) -> None:
    raw_path = ui.text("Load path", "fleet.path")
    if raw_path is None:
        return
    if session.fleet.ships and not ui.confirm("Replace the current fleet draft?"):
        return
    try:
        loaded = load_fleet(Path(raw_path))
        if loaded.faction is not session.fleet.faction:
            raise FleetSpecError(
                f"fleet is {loaded.faction.value}, session is {session.fleet.faction.value}"
            )
        validate_fleet_spec(loaded, budget=session.budget)
        if candidate_validator is not None:
            candidate_validator(deepcopy(loaded))
    except (FleetSpecError, ValueError) as exc:
        ui.show(str(exc))
        return
    session.fleet = loaded
    ui.show(f"Loaded '{loaded.name}'.")
