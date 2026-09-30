"""Stand-alone Textual app around :class:`BattleScreen`, plus :func:`run_battle`.

The battle itself lives in :mod:`spacefleet.tui.screens.battle`; this module
re-exports its public names so older imports keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App

from spacefleet.campaign.models import BattleOutcome
from spacefleet.tui.screens.battle import (
    FPS,
    MIN_SIZE,
    PLANNING,
    PLAYBACK,
    RESOLVING,
    SPEEDS,
    TURN_LIMIT,
    WIDE_COLUMNS,
    BattleScreen,
    ConfirmTurnScreen,
    HelpScreen,
    QuitScreen,
    drift_prediction,
    format_command,
    format_maneuver,
    format_pending,
    sensor_rings,
    weapon_arcs,
)

if TYPE_CHECKING:
    from spacefleet.campaign.battle import BattleSession
    from spacefleet.net.ai_controller import AIController

__all__ = [
    "FPS",
    "MIN_SIZE",
    "PLANNING",
    "PLAYBACK",
    "RESOLVING",
    "SPEEDS",
    "TURN_LIMIT",
    "WIDE_COLUMNS",
    "BattleApp",
    "BattleScreen",
    "ConfirmTurnScreen",
    "HelpScreen",
    "QuitScreen",
    "drift_prediction",
    "format_command",
    "format_maneuver",
    "format_pending",
    "run_battle",
    "sensor_rings",
    "weapon_arcs",
]


# ``inherit_bindings=False`` drops App's priority ``ctrl+q`` quit, which would
# otherwise pre-empt the battle's own ``ctrl+q`` (ask before leaving).
class BattleApp(App[BattleOutcome], inherit_bindings=False):
    """Runs one :class:`BattleScreen` and exits with its outcome."""

    def __init__(
        self,
        session: BattleSession,
        *,
        turn_limit: int = TURN_LIMIT,
        ai: AIController | None = None,
    ) -> None:
        super().__init__()
        self.battle = BattleScreen(session, turn_limit=turn_limit, ai=ai)

    def on_mount(self) -> None:
        self.push_screen(self.battle, self._on_battle_over)

    def _on_battle_over(self, outcome: BattleOutcome | None) -> None:
        self.exit(outcome)


# ── runner ──────────────────────────────────────────────────────────


def run_battle(
    session: BattleSession,
    *,
    turn_limit: int = TURN_LIMIT,
    ai: AIController | None = None,
) -> BattleOutcome:
    result = BattleApp(session, turn_limit=turn_limit, ai=ai).run()
    return BattleOutcome.ABANDONED if result is None else result
