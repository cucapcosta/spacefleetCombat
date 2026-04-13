"""Four-subsystem health tracker shared by ships and serializers."""

from __future__ import annotations

from dataclasses import dataclass

SUBSYSTEM_NAMES = ("generator", "deck", "engines", "weapons")


@dataclass
class Subsystems:
    """Operational state for the four critical ship subsystems."""

    generator: bool = True
    deck: bool = True
    engines: bool = True
    weapons: bool = True

    def all_operational(self) -> bool:
        return self.generator and self.deck and self.engines and self.weapons

    def damaged_list(self) -> list[str]:
        return [name for name in SUBSYSTEM_NAMES if not getattr(self, name)]

    def repair_all(self) -> None:
        self.generator = True
        self.deck = True
        self.engines = True
        self.weapons = True
