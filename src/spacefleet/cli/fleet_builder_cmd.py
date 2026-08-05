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
        return "not yet implemented"

    def _execute_equip(self, cmd: str, args: list[str]) -> str:
        return "not yet implemented"

    # ── Save/load (Task 7) ────────────────────────────────────

    def _save(self, args: list[str]) -> str:
        return "not yet implemented"

    def _load(self, args: list[str]) -> str:
        return "not yet implemented"

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
