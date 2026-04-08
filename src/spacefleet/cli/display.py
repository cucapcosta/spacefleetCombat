"""Text display formatting for the CLI layer.

All visual output goes through functions here so the game engine
never does I/O directly.
"""

from __future__ import annotations

# Avoid circular import — ContactInfo is only used for type hints
from typing import TYPE_CHECKING

from spacefleet.cli.colors import C, bold, colored, dim, health_bar
from spacefleet.core.types import DetectionLevel, WeaponType
from spacefleet.spatial.geometry import (
    arc_name,
    bearing_from_to,
    distance,
    is_in_arc,
    relative_bearing,
)

if TYPE_CHECKING:
    from spacefleet.combat.resolution import AttackResult
    from spacefleet.models.projectile import Projectile
    from spacefleet.models.ship import Ship
    from spacefleet.spatial.detection import ContactInfo

# Heading arrows: map rounded-to-45° heading → character
_HEADING_ARROWS: dict[int, str] = {
    0: "↑",
    45: "↗",
    90: "→",
    135: "↘",
    180: "↓",
    225: "↙",
    270: "←",
    315: "↖",
}

# ─────────────────────────────────────────────────────────────────
# Decorative lines
# ─────────────────────────────────────────────────────────────────

DIVIDER = colored("─" * 60, C.DIM)
DOUBLE_DIVIDER = colored("═" * 60, C.DIM)


# ─────────────────────────────────────────────────────────────────
# Turn header
# ─────────────────────────────────────────────────────────────────


def format_turn_header(turn: int) -> str:
    """Render the turn banner."""
    return f"\n{DOUBLE_DIVIDER}\n  {bold(f'═══  TURN {turn}  ═══')}\n{DOUBLE_DIVIDER}"


# ─────────────────────────────────────────────────────────────────
# Ship status
# ─────────────────────────────────────────────────────────────────


def format_ship_status(ship: Ship) -> str:
    """Detailed ship status readout (for the player's own ship)."""
    lines: list[str] = []

    # Header
    status = colored("DESTROYED", C.RED) if ship.is_destroyed else colored("ACTIVE", C.GREEN)
    lines.append(f"  {bold(ship.name)} [{ship.hull.classification.value}] — {status}")
    lines.append(DIVIDER)

    # Position & movement
    lines.append(f"  Position : {ship.position}")
    lines.append(f"  Heading  : {ship.heading:.0f}°")
    lines.append(f"  Speed    : {ship.speed:.0f} / {ship.speed_max:.0f} GU/turn")
    if ship.pending_turn != 0:
        direction = "starboard" if ship.pending_turn > 0 else "port"
        lines.append(f"  Turn     : {abs(ship.pending_turn):.0f}° {direction} pending")
    lines.append("")

    # Structure
    lines.append(f"  Hull     : {health_bar(ship.hull_current, ship.hull_max)}")
    lines.append(f"  Shields  : {health_bar(ship.shields_current, ship.shields_max)}")

    if ship.fires > 0:
        lines.append(f"  Fires    : {colored(f'{ship.fires} active', C.BRIGHT_RED)}")

    # Armor
    lines.append("")
    lines.append(
        f"  Armor    : Prow {ship.hull.armor_prow}"
        f"  Port {ship.hull.armor_port}"
        f"  Star {ship.hull.armor_starboard}"
        f"  Stern {ship.hull.armor_stern}"
    )

    # Stance
    lines.append("")
    stance_name = ship.stance.value.replace("_", " ").title()
    cd = ship.stance_cooldown_remaining
    cd_str = f" (locked {cd} turns)" if cd > 0 else " (can switch)"
    lines.append(f"  Stance   : {colored(stance_name, C.BRIGHT_YELLOW)}{cd_str}")

    # Morale
    from spacefleet.core.types import MoraleState

    _morale_colors = {
        MoraleState.FULL: C.GREEN,
        MoraleState.SHAKEN: C.YELLOW,
        MoraleState.WAVERING: C.BRIGHT_RED,
        MoraleState.BREAKING: C.RED,
        MoraleState.MUTINY: C.RED,
    }
    m_color = _morale_colors[ship.morale_state()]
    lines.append(
        f"  Morale   : {colored(f'{ship.morale}/{ship.morale_max}', m_color)}"
        f" ({ship.morale_state().value})"
    )

    # Combustion
    lines.append(f"  Combustn : {health_bar(ship.combustion, ship.combustion_max)}")

    # Subsystems (capital ships only)
    from spacefleet.core.types import ShipClass

    if ship.hull.classification not in (ShipClass.ESCORT,):
        parts: list[str] = []
        for label, ok in [
            ("Gen", ship.subsystem_generator),
            ("Deck", ship.subsystem_deck),
            ("Eng", ship.subsystem_engines),
            ("Wpn", ship.subsystem_weapons),
        ]:
            parts.append(colored(label, C.GREEN if ok else C.RED))
        lines.append(f"  Subsys   : {' | '.join(parts)}")

    # Weapons
    if ship.weapons:
        lines.append("")
        lines.append(f"  {bold('Weapons:')}")
        for w in ship.weapons:
            w_status = colored("READY", C.GREEN) if w.can_fire else colored("COOLDOWN", C.YELLOW)
            lines.append(
                f"    [{w.slot_id}] {w.display_name}"
                f"  ({w.arc.value}, str {w.weapon.strength},"
                f" range {w.weapon.range:.0f})"
                f"  {w_status}"
            )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Contacts / sensor readout
# ─────────────────────────────────────────────────────────────────


def _direction_label(relative_brg: float) -> str:
    """Human-friendly direction label from a relative bearing."""
    abs_rb = abs(relative_brg)
    if abs_rb <= 22.5:
        return "dead ahead"
    if abs_rb <= 67.5:
        return "off starboard bow" if relative_brg > 0 else "off port bow"
    if abs_rb <= 112.5:
        return "abeam starboard" if relative_brg > 0 else "abeam port"
    if abs_rb <= 157.5:
        return "off starboard quarter" if relative_brg > 0 else "off port quarter"
    return "astern"


def format_contact(
    ship: Ship,
    observer: Ship,
    *,
    detected: bool = True,
    contact_info: ContactInfo | None = None,
) -> str:
    """Brief contact readout as seen from *observer*.

    When *contact_info* is provided the output adapts to the
    detection level (BLIP / CONTACT / IDENTIFIED).
    """
    # ── detection-aware path ──
    if contact_info is not None:
        ci = contact_info
        friendly = ci.is_friendly

        if ci.detection_level == DetectionLevel.BLIP:
            # Use display (jittered) position for bearing / range
            approx_dist = distance(observer.position, ci.display_position)
            approx_brg = bearing_from_to(observer.position, ci.display_position)
            rel = relative_bearing(observer.heading, approx_brg)
            direction = _direction_label(rel)
            tag_color = C.CYAN if friendly else C.YELLOW
            return (
                f"  {colored('[BLIP]', tag_color)} {ci.display_name}"
                f" — bearing ~{approx_brg:.0f}° ({direction}),"
                f" ~{approx_dist:.0f} GU"
            )

        if ci.detection_level == DetectionLevel.CONTACT:
            d = distance(observer.position, ship.position)
            brg = bearing_from_to(observer.position, ship.position)
            rel = relative_bearing(observer.heading, brg)
            direction = _direction_label(rel)
            tag_color = C.CYAN if friendly else C.YELLOW
            return (
                f"  {colored('[CONTACT]', tag_color)} {ci.display_name}"
                f" — bearing {brg:.0f}° ({direction}),"
                f" range {d:.0f} GU"
            )

        # IDENTIFIED — full info
        d = distance(observer.position, ship.position)
        brg = bearing_from_to(observer.position, ship.position)
        rel = relative_bearing(observer.heading, brg)
        direction = _direction_label(rel)
        hull_str = health_bar(ship.hull_current, ship.hull_max)
        destroyed = colored(" DESTROYED", C.RED) if ship.is_destroyed else ""

        if friendly:
            tag = colored("[FLEET]", C.BRIGHT_CYAN)
            name = colored(ship.name, C.BRIGHT_CYAN)
        else:
            tag = colored("[IDENTIFIED]", C.GREEN)
            name = colored(ship.name, C.BRIGHT_RED)

        return (
            f"  {tag}"
            f" {name}"
            f" [{ship.hull.classification.value}]"
            f" — bearing {brg:.0f}° ({direction}),"
            f" range {d:.0f} GU\n"
            f"    Hull: {hull_str}"
            f"  Shields: {ship.shields_current}/{ship.shields_max}"
            f"  Speed: {ship.speed:.0f} GU/turn"
            f"  Heading: {ship.heading:.0f}°"
            f"{destroyed}"
        )

    # ── legacy path (no ContactInfo) ──
    dist_val = distance(observer.position, ship.position)
    brg = bearing_from_to(observer.position, ship.position)
    rel = relative_bearing(observer.heading, brg)
    direction = _direction_label(rel)

    if not detected:
        return (
            f"  {colored('CONTACT', C.YELLOW)}: Unidentified — "
            f"bearing {brg:.0f}° ({direction}), range {dist_val:.0f} GU"
        )

    hull_str = health_bar(ship.hull_current, ship.hull_max)
    destroyed = colored(" DESTROYED", C.RED) if ship.is_destroyed else ""

    return (
        f"  {colored(ship.name, C.BRIGHT_RED)} [{ship.hull.classification.value}]"
        f" — bearing {brg:.0f}° ({direction}), range {dist_val:.0f} GU\n"
        f"    Hull: {hull_str}  Shields: {ship.shields_current}/{ship.shields_max}"
        f"  Speed: {ship.speed:.0f} GU/turn  Heading: {ship.heading:.0f}°"
        f"{destroyed}"
    )


# ─────────────────────────────────────────────────────────────────
# Attack result
# ─────────────────────────────────────────────────────────────────


def format_attack_result(result: AttackResult) -> str:
    """Render an attack result as a combat-log entry."""
    lines: list[str] = []

    header = (
        f"  {bold(result.attacker_name)} fires "
        f"{colored(result.weapon_name, C.BRIGHT_YELLOW)}"
        f" at {colored(result.target_name, C.BRIGHT_RED)}"
    )
    lines.append(header)

    if not result.in_arc:
        lines.append(f"    {colored('\u2717 ' + result.message, C.DIM)}")
        return "\n".join(lines)

    if not result.in_range:
        lines.append(f"    {colored('\u2717 ' + result.message, C.DIM)}")
        return "\n".join(lines)

    lines.append(f"    Range: {result.distance:.0f} GU")

    # Battery specifics — full pipeline
    if result.weapon_type == WeaponType.BATTERY:
        strength = result.weapon_strength
        fp = result.effective_firepower
        fp_note = ""
        if fp < strength:
            fp_note = f" (reduced to {fp} at long range)"
        lines.append(
            f"    Broadside: {strength} guns fire{fp_note}"
            f"  Aspect: {result.target_aspect}  Column: {result.gunnery_column}"
        )
        misses = fp - result.raw_hits
        if result.raw_hits > 0:
            lines.append(
                f"    Gunnery: {colored(str(result.raw_hits), C.GREEN)}"
                f" find their mark, {colored(str(misses), C.RED)} miss"
            )
        else:
            lines.append(f"    Gunnery: {colored(f'all {fp} miss!', C.DIM)}")

    # Lance specifics — full pipeline
    if result.weapon_type == WeaponType.LANCE and result.lance_rolls:
        num_beams = result.weapon_strength
        hits = sum(1 for r in result.lance_rolls if r >= 4)
        misses = num_beams - hits
        roll_str = ", ".join(
            colored(str(r), C.GREEN if r >= 4 else C.RED) for r in result.lance_rolls
        )
        lines.append(f"    Lance battery: {num_beams} beams fired")
        lines.append(
            f"    Rolls: [{roll_str}] \u2192 "
            f"{colored(str(hits), C.GREEN)} hit (4+ needed),"
            f" {colored(str(misses), C.RED)} miss"
        )

    # Damage pipeline
    if result.raw_hits > 0:
        if result.shield_blocked:
            lines.append(f"    Shields absorb: {result.shield_blocked}")

        # Armor details (batteries only)
        if result.weapon_type == WeaponType.BATTERY and result.hit_details:
            for i, detail in enumerate(result.hit_details, 1):
                if detail.penetrated:
                    lines.append(
                        f"      Hit {i}: D6={detail.armor_roll}"
                        f" vs armor {detail.armor_value}"
                        f" \u2192 {colored('PENETRATES', C.BRIGHT_RED)}"
                    )
                else:
                    lines.append(
                        f"      Hit {i}: D6={detail.armor_roll}"
                        f" vs armor {detail.armor_value}"
                        f" \u2192 {colored('deflected', C.DIM)}"
                    )

        # Lance bypass note
        if result.weapon_type == WeaponType.LANCE and result.penetrating_hits > 0:
            lines.append(f"    {dim(f'{result.penetrating_hits} hit(s) bypass armor')}")

        if result.hull_damage_dealt > 0:
            lines.append(f"    {colored(f'Hull damage: {result.hull_damage_dealt}', C.BRIGHT_RED)}")
        elif result.raw_hits > 0 and result.hull_damage_dealt == 0:
            lines.append(f"    {dim('No hull damage dealt')}")
    elif result.weapon_type not in (WeaponType.BATTERY, WeaponType.LANCE):
        # For unimplemented weapon types
        lines.append(f"    {colored(result.message, C.DIM)}")

    if result.target_destroyed:
        lines.append(f"    {colored('*** TARGET DESTROYED ***', C.BRIGHT_RED)}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Action prompt / help
# ─────────────────────────────────────────────────────────────────


def format_available_actions(actions_remaining: int) -> str:
    """Show available player actions."""
    lines = [
        f"\n  {bold(f'Actions remaining: {actions_remaining}')}",
        "",
        f"  {colored('fire', C.BRIGHT_YELLOW)} <weapon#> <bearing>"
        "   — Fire a weapon at a bearing (e.g. fire 1 270)",
        f"  {colored('ahead', C.BRIGHT_CYAN)} [speed]"
        "               — Set speed (no arg = full, e.g. ahead 15)",
        f"  {colored('stop', C.BRIGHT_CYAN)}                       — All stop (same as ahead 0)",
        f"  {colored('turn', C.BRIGHT_CYAN)} <port|starboard> <deg>"
        " — Order a turn (executes during drift)",
        f"  {colored('pass', C.DIM)}                       — Do nothing",
        "",
        f"  {dim('Free actions (do not cost an action):')}",
        f"  {colored('status', C.GREEN)}                     — Detailed ship status",
        f"  {colored('scan', C.GREEN)}                       — View sensor contacts",
        f"  {colored('weapons', C.GREEN)}                    — List weapons with arc info",
        f"  {colored('stance', C.GREEN)} [name]"
        "              — View or switch stance",
        f"  {colored('help', C.GREEN)}                       — Show this list",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Weapon list
# ─────────────────────────────────────────────────────────────────


def format_weapons_list(
    ship: Ship,
    targets: list[Ship] | None = None,
    *,
    contact_infos: list[ContactInfo] | None = None,
) -> str:
    """Detailed weapon list showing arcs and which targets are in arc.

    When *contact_infos* is given, only targetable contacts are shown
    and CONTACT-level targets use their class name instead of full name.
    """
    lines = [f"  {bold('Weapons loadout:')}"]

    for w in ship.weapons:
        w_status = colored("READY", C.GREEN) if w.can_fire else colored("COOLDOWN", C.YELLOW)
        lines.append(f"    [{w.slot_id}] {w.display_name}")
        lines.append(
            f"        Type: {w.weapon.weapon_type.value}"
            f"  Size: {w.weapon.size.value}"
            f"  Str: {w.weapon.strength}"
            f"  Range: {w.weapon.range:.0f} GU"
            f"  Arc: {arc_name(w.arc)}"
            f"  {w_status}"
        )

        # Show which contacts are in arc — detection-aware
        if contact_infos is not None:
            for ci in contact_infos:
                if not ci.targetable:
                    continue
                t = ci.ship
                if t.is_destroyed:
                    continue
                dist_val = distance(ship.position, t.position)
                brg = bearing_from_to(ship.position, t.position)
                in_arc = is_in_arc(ship.heading, brg, w.arc)
                in_range = dist_val <= w.weapon.range
                label = ci.display_name

                if in_arc and in_range:
                    lines.append(
                        f"        → {colored(label, C.GREEN)}"
                        f" at {dist_val:.0f} GU, brg {brg:.0f}°"
                        f" — {colored('IN ARC + RANGE', C.BRIGHT_GREEN)}"
                    )
                elif in_arc:
                    lines.append(
                        f"        → {colored(label, C.YELLOW)}"
                        f" at {dist_val:.0f} GU, brg {brg:.0f}°"
                        f" — {colored('IN ARC, out of range', C.YELLOW)}"
                    )
                else:
                    lines.append(
                        f"        → {dim(label)} at {dist_val:.0f} GU — {dim('outside arc')}"
                    )
        elif targets:
            # Legacy path (no detection info)
            for t in targets:
                if t.is_destroyed:
                    continue
                dist_val = distance(ship.position, t.position)
                brg = bearing_from_to(ship.position, t.position)
                in_arc = is_in_arc(ship.heading, brg, w.arc)
                in_range = dist_val <= w.weapon.range

                if in_arc and in_range:
                    lines.append(
                        f"        → {colored(t.name, C.GREEN)}"
                        f" at {dist_val:.0f} GU"
                        f" — {colored('IN ARC + RANGE', C.BRIGHT_GREEN)}"
                    )
                elif in_arc:
                    lines.append(
                        f"        → {colored(t.name, C.YELLOW)}"
                        f" at {dist_val:.0f} GU"
                        f" — {colored('IN ARC, out of range', C.YELLOW)}"
                    )
                else:
                    lines.append(
                        f"        → {dim(t.name)} at {dist_val:.0f} GU — {dim('outside arc')}"
                    )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# End-of-turn summary
# ─────────────────────────────────────────────────────────────────


def format_end_of_turn(
    ship: Ship,
    shields_regen: int,
    fire_damage: int,
) -> str:
    """End-of-turn effects summary."""
    lines = [f"\n  {bold('End of Turn')}"]

    if shields_regen > 0:
        lines.append(
            f"    Shields regenerated: +{shields_regen} ({ship.shields_current}/{ship.shields_max})"
        )

    if fire_damage > 0:
        lines.append(
            colored(
                f"    Fire damage: {fire_damage} hull damage!",
                C.BRIGHT_RED,
            )
        )

    lines.append(f"    Hull: {health_bar(ship.hull_current, ship.hull_max)}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Kit selection
# ─────────────────────────────────────────────────────────────────


def format_kit_option(
    label: str,
    description: str,
    weapons: list[tuple[str, str, str]],
) -> str:
    """Format a weapon-kit selection option.

    *weapons* is a list of ``(slot_name, weapon_name, notes)`` tuples.
    """
    lines = [
        f"  {bold(label)}",
        f"    {description}",
    ]
    for slot, weapon, notes in weapons:
        extra = f"  {dim(notes)}" if notes else ""
        lines.append(f"      {slot}: {colored(weapon, C.BRIGHT_YELLOW)}{extra}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Drift report
# ─────────────────────────────────────────────────────────────────


def format_drift_report(
    ship: Ship,
    old_pos_str: str,
    *,
    heading_before: float | None = None,
    heading_after: float | None = None,
) -> str:
    """Drift report after time flows, with optional heading-change info."""
    heading_change = ""
    if (
        heading_before is not None
        and heading_after is not None
        and abs(heading_before - heading_after) > 0.1
    ):
        delta = heading_after - heading_before
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360
        direction = "starboard" if delta > 0 else "port"
        mode = "pivot" if ship.speed <= 0 else "during drift"
        heading_change = (
            f"\n    Heading: {heading_before:.0f}° → {heading_after:.0f}°"
            f" ({abs(delta):.0f}° {direction} {mode})"
        )

    if ship.speed > 0:
        return (
            f"  {dim('Ship drifts:')} {old_pos_str} → {ship.position}"
            f"  (heading {ship.heading:.0f}°, speed {ship.speed:.0f})"
            f"{heading_change}"
        )
    elif heading_change:
        # Stationary pivot — no position change, but heading moved
        return f"  {dim('Ship pivots in place:')}  {ship.position}{heading_change}"
    else:
        return ""


# ─────────────────────────────────────────────────────────────────
# Radar / scanner view
# ─────────────────────────────────────────────────────────────────

# Grid dimensions (odd so centre cell is exact)
_RADAR_W = 31
_RADAR_H = 17
_CENTER_X = _RADAR_W // 2
_CENTER_Y = _RADAR_H // 2


def _heading_arrow(heading: float) -> str:
    """Pick a directional arrow character for *heading* (rounded to nearest 45°)."""
    bucket = round(heading / 45) % 8
    return _HEADING_ARROWS[bucket * 45]


def format_radar_view(
    player: Ship,
    contacts: list[Ship],
    projectiles: list[Projectile] | None = None,
    *,
    contact_infos: list[ContactInfo] | None = None,
) -> str:
    """Render a north-up ASCII radar grid.

    When *contact_infos* is given, markers and legend adapt to
    detection level (BLIP ``?`` / CONTACT numbered yellow /
    IDENTIFIED numbered red).
    """
    # ── calculate scale ──────────────────────────────────────
    max_dist = 0.0

    # Use contact_infos for positions if available (jittered BLIPs)
    if contact_infos is not None:
        for ci in contact_infos:
            d = distance(player.position, ci.display_position)
            if d > max_dist:
                max_dist = d
    else:
        alive_contacts: list[Ship] = [c for c in contacts if not c.is_destroyed]
        for c in alive_contacts:
            d = distance(player.position, c.position)
            if d > max_dist:
                max_dist = d

    # Also consider projectile positions for scale
    alive_projectiles = [p for p in (projectiles or []) if p.alive]
    for p in alive_projectiles:
        d = distance(player.position, p.position)
        if d > max_dist:
            max_dist = d

    # Half-extent in GU that must fit in half the grid width/height
    half_cells = min(_CENTER_X, _CENTER_Y) - 1  # leave 1 cell border margin
    margin_dist = max_dist * 1.2 if max_dist > 0 else 20.0
    if margin_dist < 10.0:
        margin_dist = 10.0
    scale = margin_dist / half_cells  # GU per cell
    if scale < 2.0:
        scale = 2.0

    # ── build grid ───────────────────────────────────────────
    empty = (dim("\u00b7"), None)
    grid: list[list[tuple[str, str | None]]] = [[empty] * _RADAR_W for _ in range(_RADAR_H)]

    # ── place projectiles ────────────────────────────────────
    for p in alive_projectiles:
        dx = p.position.x - player.position.x
        dy = p.position.y - player.position.y
        gx = _CENTER_X + round(dx / scale)
        gy = _CENTER_Y - round(dy / scale)

        if 0 <= gx < _RADAR_W and 0 <= gy < _RADAR_H:
            proj_color = C.BRIGHT_YELLOW if p.attacker_faction == player.faction else C.BRIGHT_RED
            grid[gy][gx] = (colored("*", proj_color), None)

    # ── place contacts ───────────────────────────────────────
    legend_entries: list[str] = []
    contact_num = 0  # running counter for numbered markers

    if contact_infos is not None:
        for ci in contact_infos:
            pos = ci.display_position
            dx = pos.x - player.position.x
            dy = pos.y - player.position.y
            gx = _CENTER_X + round(dx / scale)
            gy = _CENTER_Y - round(dy / scale)

            # Bearing / distance for legend (from player to display pos)
            d_val = distance(player.position, pos)
            brg = bearing_from_to(player.position, pos)
            rel = relative_bearing(player.heading, brg)
            direction = _direction_label(rel)

            friendly = ci.is_friendly

            if ci.detection_level == DetectionLevel.BLIP:
                marker = "?"
                blip_color = C.CYAN if friendly else C.YELLOW
                marker_colored = colored(marker, blip_color)
                legend_entries.append(
                    f"    {colored(marker, blip_color)} {ci.display_name}"
                    f" \u2014 ~{d_val:.0f} GU, {direction}"
                )
            elif ci.detection_level == DetectionLevel.CONTACT:
                contact_num += 1
                marker = str(contact_num)
                contact_color = C.CYAN if friendly else C.YELLOW
                marker_colored = colored(marker, contact_color)
                legend_entries.append(
                    f"    {colored(marker, contact_color)} {ci.display_name}"
                    f" \u2014 {d_val:.0f} GU, {direction}"
                )
            else:  # IDENTIFIED
                contact_num += 1
                marker = str(contact_num)
                id_color = C.BRIGHT_CYAN if friendly else C.BRIGHT_RED
                marker_colored = colored(marker, id_color)
                legend_entries.append(
                    f"    {colored(marker, id_color)} {ci.display_name}"
                    f" \u2014 {d_val:.0f} GU, {direction}"
                )

            if 0 <= gx < _RADAR_W and 0 <= gy < _RADAR_H:
                grid[gy][gx] = (marker_colored, None)
    else:
        # Legacy path — no detection info
        alive_list = [c for c in contacts if not c.is_destroyed]
        for idx, c in enumerate(alive_list):
            dx = c.position.x - player.position.x
            dy = c.position.y - player.position.y
            gx = _CENTER_X + round(dx / scale)
            gy = _CENTER_Y - round(dy / scale)

            marker = str(idx + 1)
            if 0 <= gx < _RADAR_W and 0 <= gy < _RADAR_H:
                grid[gy][gx] = (colored(marker, C.BRIGHT_RED), None)

            dist_val = distance(player.position, c.position)
            brg = bearing_from_to(player.position, c.position)
            rel = relative_bearing(player.heading, brg)
            direction = _direction_label(rel)
            legend_entries.append(
                f"    {colored(marker, C.BRIGHT_RED)} {c.name}"
                f" \u2014 {dist_val:.0f} GU, {direction}"
            )

    # ── place player at centre ───────────────────────────────
    arrow = colored(_heading_arrow(player.heading), C.BRIGHT_CYAN)
    grid[_CENTER_Y][_CENTER_X] = (arrow, None)

    # ── render grid with border ──────────────────────────────
    lines: list[str] = []

    scale_label = f"1 char \u2248 {scale:.0f} GU"
    lines.append(f"    {bold('\u2550\u2550 SCANNER \u2550\u2550')}  ({scale_label})")

    top_border = "\u250c" + "\u2500" * (_RADAR_W * 2 + 1) + "\u2510"
    bot_border = "\u2514" + "\u2500" * (_RADAR_W * 2 + 1) + "\u2518"

    lines.append(f"    {top_border}  N")

    for row_idx, row in enumerate(grid):
        cells = " ".join(cell[0] for cell in row)
        suffix = ""
        if row_idx == 0:
            suffix = "  \u2191"
        lines.append(f"    \u2502 {cells} \u2502{suffix}")

    lines.append(f"    {bot_border}")

    # ── legend ───────────────────────────────────────────────
    if legend_entries:
        lines.append(f"    {bold('Contacts:')}")
        lines.extend(legend_entries)

    # Projectile count
    if alive_projectiles:
        n_friendly = sum(1 for p in alive_projectiles if p.attacker_faction == player.faction)
        n_enemy = len(alive_projectiles) - n_friendly
        parts = []
        if n_friendly:
            parts.append(f"{n_friendly} friendly")
        if n_enemy:
            parts.append(f"{n_enemy} enemy")
        lines.append(f"    {colored('*', C.BRIGHT_YELLOW)} Salvos in flight: {', '.join(parts)}")

    # Player indicator
    lines.append(
        f"    {colored(_heading_arrow(player.heading), C.BRIGHT_CYAN)}"
        f" {player.name} (hdg {player.heading:.0f}\u00b0, spd {player.speed:.0f})"
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Salvo / projectile display
# ─────────────────────────────────────────────────────────────────


def format_salvo_launch(
    ship_name: str,
    weapon_name: str,
    bearing: float,
    speed: float,
    max_range: float,
) -> str:
    """Format a salvo launch event."""
    return (
        f"  {bold(ship_name)} fires "
        f"{colored(weapon_name, C.BRIGHT_YELLOW)}"
        f" at bearing {bearing:.0f}\u00b0"
        f" \u2014 {colored('Salvo away!', C.BRIGHT_CYAN)}"
        f" ({speed:.0f} GU/turn, max {max_range:.0f} GU)"
    )


def format_salvo_move(proj: Projectile, old_pos_str: str) -> str:
    """Format a projectile movement report (dim/subtle)."""
    return (
        f"  {dim(f'Salvo ({proj.weapon_name}):')}"
        f" {dim(f'{old_pos_str} \u2192 {proj.position}')}"
        f" {dim(f'[{proj.distance_traveled:.0f}/{proj.max_range:.0f} GU]')}"
    )


def format_salvo_impact(result: AttackResult) -> str:
    """Format a projectile impact event + full gunnery resolution."""
    impact_header = (
        f"\n  {colored('\u2605 IMPACT:', C.BRIGHT_YELLOW)}"
        f" {colored(result.weapon_name, C.BRIGHT_YELLOW)}"
        f" salvo hits {colored(result.target_name, C.BRIGHT_RED)}!"
    )
    return impact_header + "\n" + format_attack_result(result)


def format_salvo_expired(proj: Projectile) -> str:
    """Format a projectile expiry event."""
    return (
        f"  {dim(f'Salvo ({proj.weapon_name}) expired')}"
        f" {dim(f'({proj.distance_traveled:.0f} GU traveled, no contacts hit)')}"
    )


def format_lance_miss(ship_name: str, weapon_name: str, bearing: float) -> str:
    """Format a lance that found no target."""
    return (
        f"  {bold(ship_name)} fires "
        f"{colored(weapon_name, C.BRIGHT_YELLOW)}"
        f" at bearing {bearing:.0f}\u00b0"
        f"\n    {dim(f'No target found on bearing {bearing:.0f}\u00b0')}"
    )
