"""The Spacefleet Combat Textual app: one app, every screen, entry point of ``spacefleet``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from spacefleet.tui.screens.title import TitleScreen

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from textual.screen import Screen

    from spacefleet.models.fleet_spec import FleetSpec

    ScreenFactory = Callable[[], Screen[Any]]

FAREWELL = "Ave Imperator. The Emperor protects."


# ``inherit_bindings=False`` drops App's priority ``ctrl+q`` quit, which would
# pre-empt the battle's own ``ctrl+q`` (ask before leaving). The title handles
# ``q``/``ctrl+q`` itself; the app-level binding below is a non-priority fallback.
class SpacefleetApp(App[None], inherit_bindings=False):
    """Title screen plus the campaign, online and fleet builder screens."""

    TITLE = "Spacefleet Combat"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; }
    Toast { max-width: 60; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        *,
        save_path: Path | None = None,
        campaign_factory: ScreenFactory | None = None,
        fleet_builder_factory: ScreenFactory | None = None,
        connect_factory: ScreenFactory | None = None,
    ) -> None:
        super().__init__()
        self.theme = "textual-dark"
        self.save_path = save_path
        self.campaign_factory = campaign_factory or self._default_campaign
        self.fleet_builder_factory = fleet_builder_factory or _default_fleet_builder
        self.connect_factory = connect_factory or _default_connect

    def on_mount(self) -> None:
        self.push_screen(TitleScreen(), self._on_title_closed)

    def _on_title_closed(self, _result: None) -> None:
        self.exit()

    # ── navigation (called by the title) ──────────────────────────

    def open_campaign(self) -> None:
        self.push_screen(self.campaign_factory())

    def open_connect(self) -> None:
        self.push_screen(self.connect_factory())

    def open_fleet_builder(self) -> None:
        self.push_screen(self.fleet_builder_factory(), self._on_fleet_built)

    def _on_fleet_built(self, fleet: FleetSpec | None) -> None:
        if fleet is None:
            return
        from spacefleet.models.fleet_spec import fleet_points

        self.notify(f"Fleet '{fleet.name}' — {fleet_points(fleet)} pts.")

    # ── default factories (real screens, imported lazily) ─────────

    def _default_campaign(self) -> Screen[Any]:
        from spacefleet.tui.screens.campaign import CampaignMenuScreen

        screen: Screen[Any] = CampaignMenuScreen(self.save_path)
        return screen


def _default_fleet_builder() -> Screen[Any]:
    from spacefleet.tui.screens.fleet_builder import FleetBuilderScreen

    screen: Screen[Any] = FleetBuilderScreen()
    return screen


def _default_connect() -> Screen[Any]:
    from spacefleet.tui.screens.online import ConnectScreen

    return ConnectScreen()


def main() -> None:
    """Run the game; print the farewell once the app closes."""
    SpacefleetApp().run()
    print(f"\n  {FAREWELL}\n")
