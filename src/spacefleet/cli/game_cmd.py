"""Battle command interpreter for the tech demo.

Handles the interactive turn loop: reading player commands,
dispatching actions, managing time-flow between actions, and
rendering results via the display module.
"""

from __future__ import annotations

from collections.abc import Callable

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
from spacefleet.combat.projectile_resolution import resolve_lance_ray
from spacefleet.core.game_loop import (
    apply_end_of_turn,
    check_projectile_collisions,
    cleanup_projectiles,
    move_projectiles,
)
from spacefleet.core.types import DetectionLevel
from spacefleet.dice import DiceRoller
from spacefleet.models.projectile import Projectile
from spacefleet.models.ship import Ship
from spacefleet.spatial.detection import ContactInfo, build_contact_info
from spacefleet.spatial.geometry import (
    bearing_from_to,
    is_in_arc,
)

# Type alias for the target-spawning callback
SpawnFn = Callable[[Ship, int, DiceRoller], Ship]

# Counter for unique projectile IDs
_next_projectile_id = 0


def _make_projectile_id() -> str:
    global _next_projectile_id
    _next_projectile_id += 1
    return f"salvo_{_next_projectile_id}"


class DemoBattle:
    """Interactive battle loop for the tech demo.

    The player controls a single Dauntless Light Cruiser against
    respawning target hulks.  Each turn has 2 actions with
    half-turn drifts in between.
    """

    def __init__(
        self,
        player: Ship,
        targets: list[Ship],
        dice_roller: DiceRoller,
        *,
        spawn_fn: SpawnFn | None = None,
    ) -> None:
        self.player = player
        self.targets = targets
        self.turn = 0
        self.kills = 0
        self.dice = dice_roller
        self.running = True
        self._spawn_fn = spawn_fn
        self.projectiles: list[Projectile] = []
        self._fired_this_turn: set[str] = set()

    # ── helpers ──────────────────────────────────────────────

    @property
    def active_targets(self) -> list[Ship]:
        return [t for t in self.targets if t.alive]

    @property
    def all_ships(self) -> list[Ship]:
        return [self.player] + self.targets

    def _get_contact_infos(self) -> list[ContactInfo]:
        """Build detection-aware contact list for all alive targets."""
        infos: list[ContactInfo] = []
        for t in self.active_targets:
            force_level: DetectionLevel | None = None
            if t.id in self._fired_this_turn:
                force_level = DetectionLevel.CONTACT
            info = build_contact_info(
                self.player,
                t,
                self.dice,
                force_min_level=force_level,
            )
            if info is not None:
                infos.append(info)
        return infos

    # ════════════════════════════════════════════════════════
    # Main loop
    # ════════════════════════════════════════════════════════

    def run(self) -> None:
        """Run the demo until the player quits or is destroyed."""
        self._print_intro()

        while self.running and self.player.alive:
            self.turn += 1
            self._run_turn()

        if not self.player.alive:
            print(f"\n  {colored('Your ship has been destroyed!', C.RED)}")

        print(
            f"\n  Demo complete. {bold(str(self.kills))} target(s) destroyed"
            f" in {self.turn} turn(s)."
        )
        print("  Thanks for playing!\n")

    # ── turn flow ────────────────────────────────────────────

    def _run_turn(self) -> None:
        self._fired_this_turn.clear()
        print(format_turn_header(self.turn))
        self._show_brief_status()

        # --- Action 1 ---
        self._get_and_execute_action(1)
        if not self.running:
            return

        # --- Projectiles move + collide (phase 1) ---
        self._move_and_resolve_projectiles()

        # --- Drift (1st half) ---
        self._drift_all()

        # --- Action 2 ---
        self._get_and_execute_action(2)
        if not self.running:
            return

        # --- Projectiles move + collide (phase 2) ---
        self._move_and_resolve_projectiles()

        # --- Drift (2nd half) ---
        self._drift_all()

        # --- Enemy fire (20 % per alive target) ---
        self._enemy_fire()

        # --- Projectiles move + collide (phase 3 — resolves enemy fire) ---
        self._move_and_resolve_projectiles()

        # --- End of turn effects ---
        self._end_of_turn()

        # --- Respawn if needed ---
        self._check_respawn()

    # ════════════════════════════════════════════════════════
    # Input handling
    # ════════════════════════════════════════════════════════

    def _get_and_execute_action(self, action_num: int) -> None:
        """Prompt for and execute one action (or free-action loop)."""
        actions_left = 3 - action_num  # display only

        while True:
            try:
                raw = input(f"\n  {colored(f'Action {action_num}', C.BRIGHT_CYAN)}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                self.running = False
                return

            if not raw:
                continue

            parts = raw.split()
            cmd = parts[0].lower()
            args = parts[1:]

            # ── free actions (don't cost a slot) ──
            if cmd == "status":
                print(format_ship_status(self.player))
                continue
            if cmd == "scan":
                self._show_contacts()
                continue
            if cmd == "weapons":
                contact_infos = self._get_contact_infos()
                print(
                    format_weapons_list(
                        self.player,
                        self.active_targets,
                        contact_infos=contact_infos,
                    )
                )
                continue
            if cmd in ("help", "?"):
                print(format_available_actions(actions_left))
                continue
            if cmd == "quit":
                self.running = False
                return

            # ── costed actions ──
            if cmd == "fire":
                if self._handle_fire(args):
                    return  # action consumed
                continue  # bad input — retry
            if cmd == "ahead":
                self._handle_ahead(args)
                return
            if cmd == "stop":
                self._handle_ahead(["0"])
                return
            if cmd == "turn":
                if self._handle_turn(args):
                    return
                continue
            if cmd == "pass":
                print(f"  {dim('You hold steady.')}")
                return

            print(f"  Unknown command: '{cmd}'. Type 'help' for options.")

    # ════════════════════════════════════════════════════════
    # Action handlers
    # ════════════════════════════════════════════════════════

    def _handle_fire(self, args: list[str]) -> bool:
        """Fire a weapon at a bearing.  Returns *True* if the action was consumed.

        Syntax: ``fire <weapon#> <bearing>``
        """
        if len(args) < 2:
            self._print_weapon_hint()
            return False

        # Parse weapon slot
        try:
            slot_id = int(args[0])
        except ValueError:
            print(f"  Invalid weapon number: {args[0]}")
            self._print_weapon_hint()
            return False

        weapon = next((w for w in self.player.weapons if w.slot_id == slot_id), None)
        if weapon is None:
            print(f"  No weapon in slot {slot_id}.")
            self._print_weapon_hint()
            return False

        if not weapon.can_fire:
            print(f"  {weapon.weapon.name} is on cooldown.")
            return False

        # Parse bearing
        try:
            bearing = float(args[1]) % 360.0
        except ValueError:
            print(f"  Invalid bearing: '{args[1]}'")
            return False

        # Validate bearing is within weapon arc
        if not is_in_arc(self.player.heading, bearing, weapon.arc):
            print(f"  Bearing {bearing:.0f}\u00b0 is outside {weapon.arc.value} arc.")
            return False

        # ── Lance (instant-hit ray-cast) ──
        if weapon.weapon.speed <= 0:
            result = resolve_lance_ray(
                self.player,
                weapon,
                bearing,
                self.active_targets,
                dice_roller=self.dice,
            )
            self._fired_this_turn.add(self.player.id)
            if result is None:
                print(
                    format_lance_miss(
                        self.player.name,
                        weapon.weapon.name,
                        bearing,
                    )
                )
            else:
                print(format_attack_result(result))
                if result.target_destroyed:
                    self.kills += 1
                    print(f"\n  {colored(f'Kill #{self.kills}!', C.BRIGHT_GREEN)}")
            return True

        # ── Battery (create projectile salvo) ──
        proj = Projectile(
            id=_make_projectile_id(),
            position=self.player.position,
            bearing=bearing,
            speed=weapon.weapon.speed,
            weapon_mount=weapon,
            attacker_id=self.player.id,
            attacker_name=self.player.name,
            attacker_faction=self.player.faction,
            origin=self.player.position,
            max_range=weapon.weapon.range,
        )
        self.projectiles.append(proj)
        self._fired_this_turn.add(self.player.id)
        print(
            format_salvo_launch(
                self.player.name,
                weapon.weapon.name,
                bearing,
                weapon.weapon.speed,
                weapon.weapon.range,
            )
        )
        return True

    def _handle_ahead(self, args: list[str]) -> None:
        """Set speed.  ``ahead`` = full, ``ahead <n>`` = specific, ``stop`` = 0."""
        old = self.player.speed
        spd_max = self.player.speed_max

        if not args:
            # No argument → full speed
            target = spd_max
        else:
            try:
                target = float(args[0])
            except ValueError:
                print(f"  Invalid speed: '{args[0]}'")
                print(f"  Usage: ahead [speed]  (0–{spd_max:.0f} GU/turn)")
                return

        self.player.set_speed(target)
        new = self.player.speed

        if new <= 0:
            label = colored("All stop!", C.BRIGHT_CYAN)
        elif new >= spd_max:
            label = colored("Ahead full!", C.BRIGHT_CYAN)
        else:
            label = colored(f"Ahead {new:.0f}!", C.BRIGHT_CYAN)

        print(f"  {label}  Speed: {old:.0f} \u2192 {new:.0f} GU/turn  (max {spd_max:.0f})")

    def _handle_turn(self, args: list[str]) -> bool:
        """Order a turn.  Returns *True* if action consumed.

        Format: ``turn <starboard|port> <degrees>``
        The turn executes gradually during subsequent drifts.
        """
        if len(args) < 2:
            print(
                f"  Usage: turn <starboard|port> <degrees>\n"
                f"  Example: turn starboard 45\n"
                f"  Turn rate: {self.player.turn_rate:.0f}\u00b0 per turn"
            )
            return False

        # Parse direction
        direction_str = args[0].lower()
        if direction_str in ("starboard", "stbd", "s", "right"):
            sign = 1.0
            direction_label = "starboard"
        elif direction_str in ("port", "p", "left"):
            sign = -1.0
            direction_label = "port"
        else:
            print(f"  Invalid direction: '{args[0]}'. Use 'starboard' or 'port'.")
            return False

        # Parse degrees
        try:
            degrees = float(args[1])
        except ValueError:
            print(f"  Invalid angle: '{args[1]}'")
            return False

        if degrees < 0:
            print("  Degrees must be positive. Use direction for port/starboard.")
            return False

        requested = sign * degrees
        self.player.apply_turn(requested)

        # Feedback
        turn_rate = self.player.turn_rate
        est_turns = degrees / turn_rate if turn_rate > 0 else float("inf")

        if self.player.speed <= 0:
            mode_note = (
                f"\n    {colored('Pivoting in place', C.YELLOW)}"
                f" (120% turn rate, but stationary \u2014 easier to target)"
            )
        else:
            mode_note = ""

        turn_info = (
            f"(resolves at {turn_rate:.0f}\u00b0/turn \u2014 ~{est_turns:.1f} turns to complete)"
        )
        timing = f"  {dim(turn_info)}"

        print(
            f"  {colored(f'Helm {direction_label}!', C.BRIGHT_CYAN)}"
            f"  Ordered: {degrees:.0f}\u00b0 {direction_label}"
            f"\n   {timing}{mode_note}"
        )
        return True

    # ════════════════════════════════════════════════════════
    # Display helpers
    # ════════════════════════════════════════════════════════

    def _print_weapon_hint(self) -> None:
        print(
            "  Usage: fire <weapon#> <bearing>\n"
            "  Example: fire 1 270\n"
            "  Weapons: " + ", ".join(f"[{w.slot_id}] {w.weapon.name}" for w in self.player.weapons)
        )

    def _print_intro(self) -> None:
        print(f"\n  {bold('\u2550\u2550\u2550 COMBAT ENGAGEMENT \u2550\u2550\u2550')}")
        print(f"  You are commanding the {colored(self.player.name, C.BRIGHT_CYAN)}.")
        print("  Destroy the target hulks to practice your gunnery.")
        print(
            f"  Type {colored('help', C.GREEN)} at any time for commands."
            f"  Type {colored('quit', C.RED)} to end the demo."
        )
        print(
            f"\n  Each turn you have {bold('2 actions')}."
            f"  Your ship drifts between actions based on speed & heading."
        )
        print(
            f"  Fire weapons at a {bold('bearing')} (degrees, 0\u00b0 = north)."
            f"  Batteries fire salvos that travel; lances hit instantly."
        )
        print()

    def _show_brief_status(self) -> None:
        p = self.player
        turn_str = ""
        if p.pending_turn != 0:
            direction = "stbd" if p.pending_turn > 0 else "port"
            turn_str = f"  Turn: {abs(p.pending_turn):.0f}\u00b0 {direction}"
        salvo_str = ""
        alive_salvos = [pr for pr in self.projectiles if pr.alive]
        if alive_salvos:
            salvo_str = f"  Salvos: {len(alive_salvos)} in flight"
        print(
            f"\n  {bold(p.name)}: Hull {health_bar(p.hull_current, p.hull_max)}"
            f"  Shields {p.shields_current}/{p.shields_max}"
            f"  Pos {p.position}  Hdg {p.heading:.0f}\u00b0  Spd {p.speed:.0f}"
            f"{turn_str}{salvo_str}"
        )
        contact_infos = self._get_contact_infos()
        for ci in contact_infos:
            print(format_contact(ci.ship, p, contact_info=ci))

    def _show_contacts(self) -> None:
        contact_infos = self._get_contact_infos()
        if not contact_infos and not any(p.alive for p in self.projectiles):
            print(f"  {dim('No contacts on sensors.')}")
            return
        targets = [ci.ship for ci in contact_infos]
        print(
            format_radar_view(
                self.player,
                targets,
                self.projectiles,
                contact_infos=contact_infos,
            )
        )
        for ci in contact_infos:
            print(format_contact(ci.ship, self.player, contact_info=ci))

    # ════════════════════════════════════════════════════════
    # Game mechanics
    # ════════════════════════════════════════════════════════

    def _move_and_resolve_projectiles(self) -> None:
        """Move all projectiles, check collisions, clean up expired."""
        if not self.projectiles:
            return

        # Move and get movement segments
        movements = move_projectiles(self.projectiles, fraction=0.5)

        # Show movement reports (dim)
        for proj, old_pos, _new_pos in movements:
            if proj.alive or not proj.alive:
                # Show movement even if it just expired
                old_str = repr(old_pos)
                report = format_salvo_move(proj, old_str)
                print(report)

        # Check collisions
        impacts = check_projectile_collisions(
            movements,
            self.all_ships,
            self.dice,
        )

        # Display impacts
        for proj, _target, result in impacts:
            print(format_salvo_impact(result))
            if result.target_destroyed and proj.attacker_id == self.player.id:
                self.kills += 1
                print(f"\n  {colored(f'Kill #{self.kills}!', C.BRIGHT_GREEN)}")

        # Clean up expired projectiles and show expiry messages
        expired = cleanup_projectiles(self.projectiles)
        for proj in expired:
            # Only show expiry for projectiles that weren't impacts
            # (impacts were already displayed above)
            was_impact = any(p is proj for p, _, _ in impacts)
            if not was_impact:
                print(format_salvo_expired(proj))

    def _drift_all(self) -> None:
        """Drift every ship for half a turn."""
        old_pos = repr(self.player.position)
        h_before, h_after = self.player.apply_drift(0.5)

        report = format_drift_report(
            self.player,
            old_pos,
            heading_before=h_before,
            heading_after=h_after,
        )
        if report:
            print(report)

        for t in self.active_targets:
            t.apply_drift(0.5)

    def _enemy_fire(self) -> None:
        """Each alive target has a 20 % chance to fire back.

        Battery weapons create projectiles; instant-hit weapons
        (lances, speed=0) resolve immediately.
        """
        for target in self.active_targets:
            if not target.weapons:
                continue
            if not self.dice.chance(0.20):
                continue

            weapon = target.weapons[0]

            # Compute bearing from target to player
            bearing = bearing_from_to(target.position, self.player.position)

            # Check arc
            if not is_in_arc(target.heading, bearing, weapon.arc):
                continue

            self._fired_this_turn.add(target.id)

            if weapon.weapon.speed > 0:
                # Battery — create projectile
                proj = Projectile(
                    id=_make_projectile_id(),
                    position=target.position,
                    bearing=bearing,
                    speed=weapon.weapon.speed,
                    weapon_mount=weapon,
                    attacker_id=target.id,
                    attacker_name=target.name,
                    attacker_faction=target.faction,
                    origin=target.position,
                    max_range=weapon.weapon.range,
                )
                self.projectiles.append(proj)
                print(
                    f"\n  {colored('\u26a0 INCOMING FIRE!', C.BRIGHT_RED)}"
                    f"  {target.name} fires {weapon.weapon.name}"
                    f" at bearing {bearing:.0f}\u00b0"
                )
            else:
                # Lance / instant-hit
                result = resolve_lance_ray(
                    target,
                    weapon,
                    bearing,
                    [self.player],
                    dice_roller=self.dice,
                )
                if result is not None:
                    print(f"\n  {colored('\u26a0 INCOMING FIRE!', C.BRIGHT_RED)}")
                    print(format_attack_result(result))

    def _end_of_turn(self) -> None:
        shields, fire_dmg = apply_end_of_turn(self.player)
        if shields > 0 or fire_dmg > 0:
            print(format_end_of_turn(self.player, shields, fire_dmg))

    def _check_respawn(self) -> None:
        if self.active_targets:
            return
        if self._spawn_fn is None:
            return

        new_target = self._spawn_fn(self.player, self.kills, self.dice)
        self.targets.append(new_target)

        # Detection-aware respawn message
        ci = build_contact_info(self.player, new_target, self.dice)
        if ci is None:
            # UNDETECTED — shouldn't happen with spawn distances, but handle it
            print(
                f"\n  {colored('\u2605 NEW CONTACT', C.BRIGHT_YELLOW)}:"
                f" sensors detect a faint disturbance..."
            )
        elif ci.detection_level == DetectionLevel.BLIP:
            print(
                f"\n  {colored('\u2605 NEW CONTACT', C.BRIGHT_YELLOW)}:"
                f" Unknown contact — bearing ~{ci.true_bearing:.0f}\u00b0,"
                f" ~{ci.true_distance:.0f} GU"
            )
        elif ci.detection_level == DetectionLevel.CONTACT:
            print(
                f"\n  {colored('\u2605 NEW CONTACT', C.BRIGHT_YELLOW)}:"
                f" {ci.display_name}"
                f" detected at bearing {ci.true_bearing:.0f}\u00b0,"
                f" range {ci.true_distance:.0f} GU"
            )
        else:
            # IDENTIFIED
            print(
                f"\n  {colored('\u2605 NEW CONTACT', C.BRIGHT_YELLOW)}:"
                f" {new_target.name}"
                f" detected at bearing {ci.true_bearing:.0f}\u00b0,"
                f" range {ci.true_distance:.0f} GU"
            )
