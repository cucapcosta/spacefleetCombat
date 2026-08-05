"""Interactive fleet builder — testable command interpreter + REPL wrapper.

``FleetBuilderSession.execute`` maps one input line to one output string and
never touches stdin/stdout, so tests drive it directly.  ``run_fleet_builder``
is the thin I/O loop the app menu calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    validate_ship_spec,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.core.types import Faction

_HELP = """\
Commands:
  hulls | weapons | upgrades | doctrines   — browse catalogs
  buy <hull_id> <name...>                  — buy a hull
  equip <n>                                — configure ship n (see 'help' inside)
  remove <n>                               — sell ship n
  status                                   — fleet roster + budget
  save [path] | load <path>                — persist the fleet
  done                                     — finish
"""


class FleetBuilderSession:
    """State machine for one fleet-building session."""

    def __init__(
        self,
        faction: Faction,
        budget: int = 1000,
        name: str = "My Fleet",
    ) -> None:
        self.fleet = FleetSpec(name=name, faction=faction, ships=[])
        self.budget = budget
        self.done = False
        self._equip_index: int | None = None

    # ── Public API ────────────────────────────────────────────

    @property
    def remaining(self) -> int:
        return self.budget - fleet_points(self.fleet)

    def execute(self, line: str) -> str:
        parts = line.strip().split()
        if not parts:
            return ""
        cmd, args = parts[0].lower(), parts[1:]
        if self._equip_index is not None:
            return self._execute_equip(cmd, args)
        return self._execute_top(cmd, args)

    # ── Top-level commands ────────────────────────────────────

    def _execute_top(self, cmd: str, args: list[str]) -> str:
        if cmd == "help":
            return _HELP
        if cmd == "hulls":
            rows = [
                f"  {h.id:28s} {h.classification.value:14s} {h.hull_cost:4d} pts"
                for h in HullRegistry.by_faction(self.fleet.faction)
            ]
            return "\n".join(rows) or "  (no hulls)"
        if cmd == "weapons":
            rows = [
                f"  {w.id:24s} {w.weapon_type.value:10s} {w.size.value:8s}"
                f" str {w.strength:2d}  {w.cost:4d} pts"
                for w in WeaponRegistry.all().values()
            ]
            return "\n".join(rows)
        if cmd == "upgrades":
            rows = [
                f"  {u.id:28s} {u.cost:4d} pts  {u.name}" for u in UpgradeRegistry.all().values()
            ]
            return "\n".join(rows)
        if cmd == "doctrines":
            rows = [
                f"  {d.id:28s} {d.cost:4d} pts  {d.name}"
                for d in DoctrineRegistry.for_faction(self.fleet.faction)
            ]
            return "\n".join(rows)
        if cmd == "buy":
            return self._buy(args)
        if cmd == "remove":
            return self._remove(args)
        if cmd == "equip":
            return self._enter_equip(args)
        if cmd == "status":
            return self._status()
        if cmd == "save":
            return self._save(args)
        if cmd == "load":
            return self._load(args)
        if cmd in ("done", "quit", "exit"):
            self.done = True
            return f"Fleet '{self.fleet.name}' — {fleet_points(self.fleet)} pts."
        return f"unknown command: {cmd!r} (try 'help')"

    def _buy(self, args: list[str]) -> str:
        if len(args) < 2:
            return "usage: buy <hull_id> <name...>"
        hull_id, name = args[0], " ".join(args[1:])
        spec = ShipSpec(name=name, hull_id=hull_id)
        self.fleet.ships.append(spec)
        error = self._revalidate()
        if error:
            self.fleet.ships.pop()
            return error
        return (
            f"Bought {hull_id} as '{name}'. ({ship_points(spec)} pts — {self.remaining} remaining)"
        )

    def _remove(self, args: list[str]) -> str:
        idx = self._ship_index(args)
        if idx is None:
            return "usage: remove <ship number>"
        spec = self.fleet.ships.pop(idx)
        if self.fleet.flagship_index >= len(self.fleet.ships):
            self.fleet.flagship_index = 0
        return f"Removed '{spec.name}'. ({self.remaining} pts remaining)"

    def _status(self) -> str:
        if not self.fleet.ships:
            return f"Empty fleet. Budget: {self.budget} pts."
        rows = []
        for i, s in enumerate(self.fleet.ships):
            flag = " [FLAG]" if i == self.fleet.flagship_index else ""
            rows.append(f"  [{i + 1}] {s.name:24s} {s.hull_id:26s} {ship_points(s):4d} pts{flag}")
        rows.append(
            f"  Total {fleet_points(self.fleet)} / {self.budget} pts — {self.remaining} remaining"
        )
        return "\n".join(rows)

    # ── Equip sub-mode (Task 7) ───────────────────────────────

    def _enter_equip(self, args: list[str]) -> str:
        idx = self._ship_index(args)
        if idx is None:
            return "usage: equip <ship number>"
        self._equip_index = idx
        return f"Equipping '{self.fleet.ships[idx].name}' — {self._show_ship()}"

    def _execute_equip(self, cmd: str, args: list[str]) -> str:
        assert self._equip_index is not None
        ship = self.fleet.ships[self._equip_index]
        if cmd in ("back", "done"):
            self._equip_index = None
            return self._status()
        if cmd == "show":
            return self._show_ship()
        if cmd == "help":
            return (
                "Equip commands: show | slot <n> <weapon_id> | unslot <n>"
                " | upgrade <id> | remove-upgrade <id> | doctrine <id|none>"
                " | flagship | default | back"
            )
        if cmd == "slot" and len(args) == 2 and args[0].isdigit():
            return self._mutate(
                ship,
                lambda: ship.weapons.__setitem__(int(args[0]), args[1]),
                f"Equipped {args[1]} in slot {args[0]}.",
            )
        if cmd == "unslot" and len(args) == 1 and args[0].isdigit():
            slot = int(args[0])
            if slot not in ship.weapons:
                return f"slot {slot} is empty"
            return self._mutate(
                ship,
                lambda: ship.weapons.pop(slot),
                f"Cleared slot {slot}.",
            )
        if cmd == "upgrade" and len(args) == 1:
            if args[0] in ship.upgrade_ids:
                return f"{args[0]} already installed"
            return self._mutate(
                ship,
                lambda: ship.upgrade_ids.append(args[0]),
                f"Installed {args[0]}.",
            )
        if cmd == "remove-upgrade" and len(args) == 1:
            if args[0] not in ship.upgrade_ids:
                return f"{args[0]} is not installed"
            return self._mutate(
                ship,
                lambda: ship.upgrade_ids.remove(args[0]),
                f"Removed {args[0]}.",
            )
        if cmd == "doctrine" and len(args) == 1:
            new = None if args[0] in ("none", "clear") else args[0]
            return self._mutate(
                ship,
                lambda: setattr(ship, "doctrine_id", new),
                f"Doctrine set to {new or 'none'}.",
            )
        if cmd == "flagship":
            old = self.fleet.flagship_index
            self.fleet.flagship_index = self._equip_index
            error = self._revalidate()
            if error:
                self.fleet.flagship_index = old
                return error
            return f"'{ship.name}' is now the flagship."
        if cmd == "default":
            from spacefleet.models.fleet_spec import apply_default_loadout

            snapshot = (dict(ship.weapons), list(ship.upgrade_ids), ship.doctrine_id)
            apply_default_loadout(ship)
            error = self._revalidate()
            if error:
                ship.weapons, ship.upgrade_ids, ship.doctrine_id = (
                    dict(snapshot[0]),
                    list(snapshot[1]),
                    snapshot[2],
                )
                return error
            return f"Applied default loadout. ({ship_points(ship)} pts)"
        return f"unknown equip command: {cmd!r} (try 'help')"

    def _mutate(self, ship: ShipSpec, action: Callable[[], object], ok: str) -> str:
        """Apply a mutation transactionally: snapshot → act → validate → revert on error."""
        snapshot = (dict(ship.weapons), list(ship.upgrade_ids), ship.doctrine_id)
        action()
        error = self._revalidate()
        if error:
            ship.weapons, ship.upgrade_ids, ship.doctrine_id = (
                dict(snapshot[0]),
                list(snapshot[1]),
                snapshot[2],
            )
            return error
        return f"{ok} ({self.remaining} pts remaining)"

    def _show_ship(self) -> str:
        assert self._equip_index is not None
        ship = self.fleet.ships[self._equip_index]
        hull = HullRegistry.get_or_none(ship.hull_id)
        rows = [f"  {ship.name} ({ship.hull_id}) — {ship_points(ship)} pts"]
        if hull is not None:
            for slot in hull.weapon_slots:
                fitted = ship.weapons.get(slot.id, "EMPTY")
                rows.append(f"    [{slot.id}] {slot.name:24s} {slot.size.value:8s} — {fitted}")
        rows.append(f"    upgrades: {', '.join(ship.upgrade_ids) or '(none)'}")
        rows.append(f"    doctrine: {ship.doctrine_id or '(none)'}")
        return "\n".join(rows)

    # ── Save/load (Task 7) ────────────────────────────────────

    def _save(self, args: list[str]) -> str:
        from pathlib import Path

        from spacefleet.persistence.fleet_save import default_fleet_dir, save_fleet

        if args:
            path = Path(" ".join(args))
        else:
            safe = self.fleet.name.lower().replace(" ", "_")
            path = default_fleet_dir() / f"{safe}.json"
        try:
            written = save_fleet(self.fleet, path)
        except OSError as exc:
            return f"save failed: {exc}"
        return f"Saved to {written}"

    def _load(self, args: list[str]) -> str:
        from pathlib import Path

        from spacefleet.persistence.fleet_save import load_fleet

        if not args:
            return "usage: load <path>"
        try:
            loaded = load_fleet(Path(" ".join(args)))
        except FleetSpecError as exc:
            return str(exc)
        if loaded.faction is not self.fleet.faction:
            return f"fleet is {loaded.faction.value}, session is {self.fleet.faction.value}"
        backup, self.fleet = self.fleet, loaded
        error = self._revalidate()
        if error:
            self.fleet = backup
            return error
        return f"Loaded '{self.fleet.name}' — {self._status()}"

    # ── Shared helpers ────────────────────────────────────────

    def _ship_index(self, args: list[str]) -> int | None:
        if len(args) != 1 or not args[0].isdigit():
            return None
        idx = int(args[0]) - 1
        if not (0 <= idx < len(self.fleet.ships)):
            return None
        return idx

    def _revalidate(self) -> str | None:
        """Validate the whole draft; return an error string or None."""
        try:
            for i, ship in enumerate(self.fleet.ships):
                validate_ship_spec(
                    ship,
                    self.fleet.faction,
                    is_flagship=(i == self.fleet.flagship_index),
                )
            if fleet_points(self.fleet) > self.budget:
                return f"over budget: {fleet_points(self.fleet)} > {self.budget} pts"
        except (FleetSpecError, ValueError) as exc:
            return str(exc)
        return None
