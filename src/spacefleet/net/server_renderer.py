"""Server-side rendering — per-player views using existing display.py.

Calls the pure formatting functions from ``cli/display.py`` to produce
ANSI-formatted text for each player's perspective, respecting the
detection/fog-of-war system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.cli.colors import C, bold, colored, dim, health_bar
from spacefleet.cli.display import (
    format_attack_result,
    format_available_actions,
    format_contact,
    format_drift_report,
    format_end_of_turn,
    format_lance_miss,
    format_radar_view,
    format_salvo_expired,
    format_salvo_impact,
    format_salvo_launch,
    format_salvo_move,
    format_ship_status,
    format_turn_header,
    format_weapons_list,
)
from spacefleet.core.types import DetectionLevel
from spacefleet.net.turn_resolver import (
    CriticalHitEvent,
    DestroyedEvent,
    DriftEvent,
    EndOfTurnEvent,
    FireExtinguishedEvent,
    LanceFireEvent,
    LightningStrikeEvent,
    MoraleChangeEvent,
    RespawnEvent,
    SalvoExpiredEvent,
    SalvoImpactEvent,
    SalvoLaunchEvent,
    SalvoMoveEvent,
    SpeedChangeEvent,
    StanceChangeEvent,
    TurnEvent,
    TurnLog,
    TurnOrderEvent,
)
from spacefleet.spatial.detection import ContactInfo, best_detection_level, build_contact_info
from spacefleet.spatial.geometry import distance

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.net.game_state import GameState


class ServerRenderer:
    """Produces per-player ANSI text using the authoritative game state."""

    # ── Turn header + deferred results ────────────────────────

    def render_turn_header_with_results(
        self,
        player_id: str,
        state: GameState,
        last_log: TurnLog | None = None,
    ) -> str:
        """Turn header + previous turn's combat results + salvos in flight.

        Per-ship status is no longer shown here — it is sent individually
        via ``render_ship_brief`` right before each ship's command prompt.
        """
        lines: list[str] = []
        lines.append(format_turn_header(state.turn))

        # Show deferred results from the previous turn
        if last_log is not None:
            result_text = self.render_turn_result(player_id, last_log, state)
            lines.append(result_text)

        # Salvos in flight
        alive_salvos = [p for p in state.projectiles if p.alive]
        if alive_salvos:
            lines.append(f"\n  Salvos in flight: {len(alive_salvos)}")

        return "\n".join(lines)

    # ── Per-ship brief status ──────────────────────────────

    def render_ship_brief(
        self,
        ship: Ship,
        state: GameState,
        player_id: str,
    ) -> str:
        """Brief status + contacts for a single ship (shown before its prompt)."""
        lines: list[str] = []

        turn_str = ""
        if ship.pending_turn != 0:
            direction = "stbd" if ship.pending_turn > 0 else "port"
            turn_str = f"  Turn: {abs(ship.pending_turn):.0f}\u00b0 {direction}"

        stance_short = ship.stance.value.replace("_", " ").title()
        lines.append(
            f"\n  {bold(ship.name)}:"
            f" Hull {health_bar(ship.hull_current, ship.hull_max)}"
            f"  Shields {ship.shields_current}/{ship.shields_max}"
            f"  [{colored(stance_short, C.BRIGHT_YELLOW)}]"
            f"  Morale {ship.morale}"
            f"  Pos {ship.position}  Hdg {ship.heading:.0f}\u00b0"
            f"  Spd {ship.speed:.0f}{turn_str}"
        )

        # Contacts visible from this ship (merged fleet sensors)
        contacts = self._get_contacts(ship, state, player_id)
        for ci in contacts:
            lines.append(format_contact(ci.ship, ship, contact_info=ci))

        return "\n".join(lines)

    # ── Ship prompt ──────────────────────────────────────────

    def render_prompt(
        self,
        ship: Ship,
        ship_index: int,
        total_ships: int,
        state: GameState,
        player_id: str | None = None,
    ) -> str:
        """Command prompt text for a specific ship."""
        fleet_str = f" ({ship_index}/{total_ships})" if total_ships > 1 else ""
        contacts = self._get_contacts(ship, state, player_id)
        n_enemies = sum(1 for ci in contacts if not ci.is_friendly)
        n_allies = sum(1 for ci in contacts if ci.is_friendly)
        parts: list[str] = []
        if n_enemies:
            parts.append(f"{n_enemies} hostile(s)")
        if n_allies:
            parts.append(f"{n_allies} friendly")
        contact_summary = f"  [{', '.join(parts)}]" if parts else ""
        return (
            f"\n  {colored(f'Command for {ship.name}', C.BRIGHT_CYAN)}{fleet_str}{contact_summary}"
        )

    # ── Query responses ──────────────────────────────────────

    def render_query(
        self,
        player_id: str,
        ship: Ship,
        query: str,
        state: GameState,
    ) -> str:
        """Render a free-action query (status, scan, weapons)."""
        if query == "status":
            return format_ship_status(ship)

        if query == "scan":
            contacts = self._get_contacts(ship, state, player_id)
            if not contacts and not any(p.alive for p in state.projectiles):
                return f"  {dim('No contacts on sensors.')}"
            targets = [ci.ship for ci in contacts]
            radar = format_radar_view(
                ship,
                targets,
                state.projectiles,
                contact_infos=contacts,
            )
            contact_lines = [format_contact(ci.ship, ship, contact_info=ci) for ci in contacts]
            return radar + "\n" + "\n".join(contact_lines)

        if query == "weapons":
            contacts = self._get_contacts(ship, state, player_id)
            enemies = [ci.ship for ci in contacts if ci.targetable]
            return format_weapons_list(ship, enemies, contact_infos=contacts)

        if query in ("help", "?"):
            return format_available_actions(0)

        return f"  Unknown query: '{query}'"

    # ── Turn result narration ────────────────────────────────

    def render_turn_result(
        self,
        player_id: str,
        log: TurnLog,
        state: GameState,
    ) -> str:
        """Render the full turn resolution from this player's perspective."""
        lines: list[str] = []
        # Include dead ships too (they might have been alive at turn start)
        all_player_ship_ids = set(state.player_ships.get(player_id, []))

        for event in log.events:
            rendered = self._render_event(event, player_id, all_player_ship_ids, state)
            if rendered:
                lines.append(rendered)

        if not lines:
            lines.append(f"  {dim('Nothing noteworthy happened.')}")

        return "\n".join(lines)

    # ── Game over ────────────────────────────────────────────

    def render_game_over(
        self,
        player_id: str,
        state: GameState,
    ) -> str:
        """End-of-game summary."""
        kills = state.kills.get(player_id, 0)
        lines = [
            f"\n  {bold('\u2550\u2550\u2550 GAME OVER \u2550\u2550\u2550')}",
            f"  Turns played: {state.turn}",
            f"  Your kills: {kills}",
        ]
        # Show all players' scores
        for pid, k in sorted(state.kills.items()):
            marker = " \u2190 you" if pid == player_id else ""
            lines.append(f"    {pid}: {k} kills{marker}")
        return "\n".join(lines)

    # ── Internal helpers ─────────────────────────────────────

    def _get_contacts(
        self,
        observer: Ship,
        state: GameState,
        player_id: str | None = None,
    ) -> list[ContactInfo]:
        """Build detection-aware contact list visible from *observer*.

        Includes three categories:

        * **Own fleet** (same player) — always IDENTIFIED, not targetable.
        * **Allied ships** (same faction, different player) — detected using
          merged sensor data from all the player's alive ships.
        * **Enemy ships** — detected using merged sensor data from all the
          player's alive ships.

        When *player_id* is given, all the player's ships share sensors
        (best detection level across the fleet wins).
        """
        infos: list[ContactInfo] = []

        # Collect the player's fleet for sensor sharing
        if player_id is not None:
            player_ship_ids = set(state.player_ships.get(player_id, []))
            fleet = [state.get_ship(sid) for sid in player_ship_ids if state.get_ship(sid).alive]
        else:
            player_ship_ids = {observer.id}
            fleet = [observer]

        for ship in state.ships.values():
            if ship.id == observer.id:
                continue
            if not ship.alive:
                continue

            is_own_fleet = ship.id in player_ship_ids
            is_friendly = ship.faction == observer.faction

            # ── Own fleet ships: always IDENTIFIED ──
            if is_own_fleet:
                force_level: DetectionLevel | None = DetectionLevel.IDENTIFIED
            else:
                # ── Merged detection across the player's fleet ──
                fire_boost: DetectionLevel | None = None
                if ship.id in state.fired_this_turn:
                    fire_boost = DetectionLevel.CONTACT
                merged = best_detection_level(
                    fleet,
                    ship,
                    force_min_level=fire_boost,
                )
                force_level = merged if merged != DetectionLevel.UNDETECTED else None

            ci = build_contact_info(
                observer,
                ship,
                state.dice,
                force_min_level=force_level,
            )
            if ci is not None:
                ci.is_friendly = is_friendly or is_own_fleet
                if ci.is_friendly:
                    ci.targetable = False
                infos.append(ci)

        return infos

    def _render_event(
        self,
        event: TurnEvent,
        player_id: str,
        player_ship_ids: set[str],
        state: GameState,
    ) -> str | None:
        """Render a single event.  Returns None if not visible to this player."""

        if isinstance(event, LanceFireEvent):
            if event.ship.id in player_ship_ids:
                # Player's own lance fire — always visible
                if event.result is None:
                    return format_lance_miss(
                        event.ship.name,
                        event.weapon_name,
                        event.bearing,
                    )
                return format_attack_result(event.result)
            # Enemy lance fire — visible if any player ship can see it
            if self._is_near_player(event.ship, player_ship_ids, state):
                if event.result is None:
                    return f"  {
                        dim(
                            f'Enemy lance fire at bearing {event.bearing:.0f}\u00b0 — no target hit'
                        )
                    }"
                return (
                    f"  {colored('\u26a0 INCOMING FIRE!', C.BRIGHT_RED)}\n"
                    + format_attack_result(event.result)
                )
            return None

        if isinstance(event, SalvoLaunchEvent):
            if event.ship.id in player_ship_ids:
                return format_salvo_launch(
                    event.ship.name,
                    event.weapon_name,
                    event.bearing,
                    event.speed,
                    event.max_range,
                )
            if self._is_near_player(event.ship, player_ship_ids, state):
                return (
                    f"  {colored('\u26a0 INCOMING FIRE!', C.BRIGHT_RED)}"
                    f"  {event.ship.name} fires"
                    f" {event.weapon_name}"
                    f" at bearing {event.bearing:.0f}\u00b0"
                )
            return None

        if isinstance(event, SalvoMoveEvent):
            # Show salvo movements for player's own salvos or nearby
            if event.proj.attacker_id in player_ship_ids:
                return format_salvo_move(event.proj, repr(event.old_pos))
            return None  # Skip enemy salvo movements for brevity

        if isinstance(event, SalvoImpactEvent):
            # Always show if involves player's ships (attacker or target)
            if event.proj.attacker_id in player_ship_ids or event.target.id in player_ship_ids:
                text = format_salvo_impact(event.result)
                if event.result.target_destroyed:
                    owner = state.owner_of(event.proj.attacker_id)
                    if owner == player_id:
                        kills = state.kills.get(player_id, 0)
                        text += f"\n  {colored(f'Kill #{kills}!', C.BRIGHT_GREEN)}"
                return text
            if self._is_near_player(event.target, player_ship_ids, state):
                return format_salvo_impact(event.result)
            return None

        if isinstance(event, SalvoExpiredEvent):
            if event.proj.attacker_id in player_ship_ids:
                return format_salvo_expired(event.proj)
            return None

        if isinstance(event, SpeedChangeEvent):
            if event.ship.id in player_ship_ids:
                label = f"Speed: {event.old_speed:.0f} \u2192 {event.new_speed:.0f} GU/turn"
                return f"  {colored(event.ship.name, C.BRIGHT_CYAN)}: {label}"
            return None

        if isinstance(event, TurnOrderEvent):
            if event.ship.id in player_ship_ids:
                return (
                    f"  {colored(f'Helm {event.direction}!', C.BRIGHT_CYAN)}"
                    f"  {event.ship.name}: {event.degrees:.0f}\u00b0 {event.direction}"
                )
            return None

        if isinstance(event, DriftEvent):
            if event.ship.id in player_ship_ids:
                return format_drift_report(
                    event.ship,
                    event.old_pos_str,
                    heading_before=event.heading_before,
                    heading_after=event.heading_after,
                )
            return None

        if isinstance(event, EndOfTurnEvent):
            if event.ship.id in player_ship_ids:
                return format_end_of_turn(
                    event.ship,
                    event.shields_regen,
                    event.fire_damage,
                )
            return None

        if isinstance(event, DestroyedEvent):
            if event.ship.id in player_ship_ids:
                return f"  {colored(f'{event.ship.name} has been destroyed!', C.RED)}"
            return f"  {colored(f'{event.ship.name} destroyed!', C.BRIGHT_GREEN)}"

        if isinstance(event, RespawnEvent):
            return (
                f"  {colored('\u2605 NEW CONTACT', C.BRIGHT_YELLOW)}: {event.ship.name} detected!"
            )

        if isinstance(event, StanceChangeEvent):
            if event.ship.id in player_ship_ids:
                old = event.old_stance.value.replace("_", " ").title()
                new = event.new_stance.value.replace("_", " ").title()
                reason = f" ({event.reason})" if event.reason else ""
                return (
                    f"  {colored(event.ship.name, C.BRIGHT_CYAN)}:"
                    f" Stance {old} → {colored(new, C.BRIGHT_YELLOW)}{reason}"
                )
            return None

        if isinstance(event, MoraleChangeEvent):
            if event.ship.id in player_ship_ids:
                delta = event.new_morale - event.old_morale
                sign = "+" if delta > 0 else ""
                color = C.GREEN if delta > 0 else C.RED
                return (
                    f"  {event.ship.name}: Morale"
                    f" {colored(f'{sign}{delta}', color)}"
                    f" ({event.new_morale}/{event.ship.morale_max})"
                    f" [{event.source}]"
                )
            return None

        if isinstance(event, CriticalHitEvent):
            crit = event.result
            if event.ship.id in player_ship_ids:
                extra = ""
                if hasattr(crit, "extra_damage") and crit.extra_damage > 0:
                    extra = f" (+{crit.extra_damage} hull damage)"
                return (
                    f"  {colored('CRITICAL HIT!', C.BRIGHT_RED)}"
                    f" {event.ship.name}: {crit.name}{extra}"
                )
            if self._is_near_player(event.ship, player_ship_ids, state):
                return f"  {colored('Critical!', C.BRIGHT_GREEN)} {event.ship.name}: {crit.name}"
            return None

        if isinstance(event, LightningStrikeEvent):
            b_result = event.result
            if event.attacker.id in player_ship_ids:
                return (
                    f"  {colored('LIGHTNING STRIKE!', C.BRIGHT_CYAN)}"
                    f" {event.attacker.name} \u2192 {event.target.name}:"
                    f" {b_result.message}"
                )
            if event.target.id in player_ship_ids:
                return (
                    f"  {colored('\u26a1 BOARDED!', C.BRIGHT_RED)}"
                    f" {event.attacker.name} strikes {event.target.name}:"
                    f" {b_result.message}"
                )
            return None

        if isinstance(event, FireExtinguishedEvent):
            if event.ship.id in player_ship_ids:
                return (
                    f"  {event.ship.name}:"
                    f" Fire extinguished (D6={event.roll},"
                    f" {event.fires_remaining} remaining)"
                )
            return None

        return None

    def _is_near_player(
        self,
        ship: Ship,
        player_ship_ids: set[str],
        state: GameState,
        max_range: float = 100.0,
    ) -> bool:
        """Check if *ship* is near any of the player's ships (for visibility)."""
        for sid in player_ship_ids:
            ps = state.ships.get(sid)
            if ps and ps.alive and distance(ps.position, ship.position) <= max_range:
                return True
        return False
