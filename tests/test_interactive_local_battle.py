from __future__ import annotations

from copy import deepcopy

import pytest

from spacefleet.campaign.battle import build_battle
from spacefleet.campaign.models import BattleOutcome
from spacefleet.cli import local_battle
from spacefleet.cli.display import format_radar_view
from spacefleet.cli.local_battle import LocalBattleController, _PendingTurn
from spacefleet.cli.terminal_ui import TerminalClosed
from spacefleet.commander.commander import AbilityState
from spacefleet.core.types import DetectionLevel, Faction, Stance, Vector2D
from spacefleet.net.commands import AbilityOrder, Command
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.net.turn_resolver import TurnLog
from spacefleet.spatial.detection import ContactInfo
from tests.campaign_helpers import campaign_state
from tests.terminal_ui_helpers import FakeTerminalUI


def _controller(ui: FakeTerminalUI) -> LocalBattleController:
    return LocalBattleController(build_battle(campaign_state()), ui=ui)


def test_fire_cascade_parses_and_validates_weapon_and_bearing() -> None:
    ui = FakeTerminalUI(choices=["fire", "manual", "slot:3", "done", "done"], texts=["0"])
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]

    command = controller._attack_menu(ship)

    assert command == Command(
        ship.id,
        "fire",
        {"shots": [{"slot": 3, "bearing": 0.0}]},
    )
    assert ui.text_calls == [
        ("Bearing rel. to prow (0 ahead, 90 starboard, 270 port)", "battle.fire.bearing", "")
    ]


def test_turn_cascade_collects_direction_and_angle() -> None:
    ui = FakeTerminalUI(choices=["turn", "port"], texts=["45"])
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]

    command = controller._move_menu(ship)

    assert command == Command(ship.id, "turn", {"direction": "port", "degrees": 45.0})


def test_nested_cancellation_returns_one_level() -> None:
    ui = FakeTerminalUI(
        choices=["fire", "manual", "back", "back"],
        texts=[None],
    )
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]

    assert controller._attack_menu(ship) is None
    assert [call[0] for call in ui.choose_calls] == [
        f"Attack — {ship.name}",
        f"Fire salvo — {ship.name}",
        f"Fire salvo — {ship.name}",
        f"Attack — {ship.name}",
    ]


def test_salvo_queues_all_eligible_weapons_at_one_sensor_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = FakeTerminalUI(choices=["contact:0", "all", "done", "done"])
    controller = _controller(ui)
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[1]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    contact = ContactInfo(
        target,
        DetectionLevel.IDENTIFIED,
        10,
        0,
        Vector2D(ship.position.x, ship.position.y + 10),
        target.name,
        True,
        False,
    )
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: [contact])

    command = controller._fire_menu(ship)

    assert command == Command(
        ship.id,
        "fire",
        {
            "shots": [
                {"slot": 1, "bearing": 0.0, "target": target.id},
                {"slot": 2, "bearing": 0.0, "target": target.id},
            ]
        },
    )


def test_salvo_can_queue_port_and_starboard_at_distinct_bearings() -> None:
    ui = FakeTerminalUI(
        choices=[
            "manual",
            "slot:1",
            "done",
            "manual",
            "slot:2",
            "done",
            "done",
        ],
        texts=["270", "90"],
    )
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]

    command = controller._fire_menu(ship)

    assert command == Command(
        ship.id,
        "fire",
        {
            "shots": [
                {"slot": 1, "bearing": 270.0},
                {"slot": 2, "bearing": 90.0},
            ]
        },
    )


def test_clearing_or_cancelling_salvo_does_not_change_state_or_rng() -> None:
    ui = FakeTerminalUI(
        choices=["manual", "slot:3", "done", "clear", "back"],
        texts=["0"],
    )
    controller = _controller(ui)
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    ships_before = deepcopy(state.ships)
    projectiles_before = deepcopy(state.projectiles)
    turn_before = state.turn
    rng_before = deepcopy(state.dice._rng.getstate())

    assert controller._fire_menu(ship) is None

    assert state.ships == ships_before
    assert state.projectiles == projectiles_before
    assert state.turn == turn_before
    assert state.dice._rng.getstate() == rng_before


def test_fire_contact_context_explains_arc_range_cooldown_and_damage() -> None:
    controller = _controller(FakeTerminalUI())
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    ship.weapons[0].can_fire = False
    ship.weapons[0].cooldown = 2
    ship.weapons[2].can_fire = False
    contact = ContactInfo(
        target,
        DetectionLevel.IDENTIFIED,
        100,
        90,
        Vector2D(ship.position.x + 100, ship.position.y),
        target.name,
        True,
        False,
    )

    details = controller._fire_contact_details(ship, contact, set())

    assert "cooldown for 2 more turn(s)" in details
    assert "no intercept within range" in details
    assert "disabled by damage" in details


def _identified_contact(target, position: Vector2D) -> ContactInfo:
    return ContactInfo(target, DetectionLevel.IDENTIFIED, 0, 0, position, target.name, True, False)


def test_fire_menu_labels_contacts_with_ready_weapon_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = FakeTerminalUI(choices=["back"])
    controller = _controller(ui)
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    target.speed = 0.0
    in_prow = _identified_contact(target, Vector2D(ship.position.x, ship.position.y + 20))
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: [in_prow])

    controller._fire_menu(ship)

    option = ui.choose_calls[0][1][0]
    assert option.label == f"{target.name} — 1/3 weapon(s) ready"
    assert option.disabled_reason is None
    assert "READY" in option.details


def test_contact_fire_queues_lead_bearing_for_moving_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = FakeTerminalUI(choices=["contact:0", "slot:2", "done", "done"])
    controller = _controller(ui)
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    target.heading = 0.0
    target.speed = 20.0
    abeam = _identified_contact(target, Vector2D(ship.position.x + 30, ship.position.y))
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: [abeam])

    command = controller._fire_menu(ship)

    assert command is not None
    (shot,) = command.args["shots"]
    assert shot["slot"] == 2
    # Target runs north, so the starboard battery leads it ahead of 90°.
    assert shot["bearing"] == pytest.approx(56.31, abs=0.01)
    assert "lead" in ui.choose_calls[0][1][0].details


def test_fire_menu_disables_contact_without_firing_solution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = FakeTerminalUI(choices=["back"])
    controller = _controller(ui)
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    target.speed = 0.0
    astern = _identified_contact(target, Vector2D(ship.position.x, ship.position.y - 20))
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: [astern])

    controller._fire_menu(ship)

    option = ui.choose_calls[0][1][0]
    assert option.label.endswith("no firing solution")
    assert option.disabled_reason == "No weapon can fire: 3 out of arc."
    assert controller._attack_summary(ship).startswith("No firing solution")


def test_fire_menu_explains_empty_sensor_picture(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = FakeTerminalUI(choices=["back"])
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: [])

    controller._fire_menu(ship)

    assert "No hostile contacts on sensors" in ui.choose_calls[0][2]
    assert controller._attack_summary(ship).startswith("No hostile on sensors")


def test_blip_fire_context_uses_only_approximate_display_data() -> None:
    controller = _controller(FakeTerminalUI())
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    contact = ContactInfo(
        target,
        DetectionLevel.BLIP,
        999,
        123,
        Vector2D(ship.position.x + 10, ship.position.y),
        "Unknown contact",
        False,
        False,
    )

    context = controller._fire_context(ship, [contact], [])
    details = controller._fire_contact_details(ship, contact, set())

    assert "Unknown contact: bearing ~90° rel, distance ~10 GU" in context
    assert "Bearing ~90° rel; distance ~10 GU" in details
    assert target.name not in context + details
    assert target.id not in context + details


def test_cancel_boarding_target_returns_to_attack_menu() -> None:
    ui = FakeTerminalUI(choices=["boarding", None, "back"])
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]

    assert controller._attack_menu(ship) is None
    assert [call[0] for call in ui.choose_calls] == [
        f"Attack — {ship.name}",
        "Boarding target",
        f"Attack — {ship.name}",
    ]


def test_tactic_queries_and_stance_do_not_advance_state() -> None:
    ui = FakeTerminalUI(choices=["status", "scan", "weapons", "stance", "lock_on", "back"])
    controller = _controller(ui)
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    rng_before = deepcopy(state.dice._rng.getstate())
    pending = _PendingTurn()

    controller._tactic_menu(ship, pending)

    assert state.turn == 0
    assert state.dice._rng.getstate() == rng_before
    assert pending.stances == {ship.id: Stance.LOCK_ON}
    assert len(ui.show_calls) == 3


def test_action_root_is_two_by_two_and_escape_redisplays() -> None:
    ui = FakeTerminalUI(choices=[None, "wait"])
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]
    pending = _PendingTurn()

    assert controller._collect_ship_order(ship, pending) is None

    assert len(ui.choose_calls[0][1]) == 4
    assert ui.choose_calls[0][3] == 2
    assert pending.commands[ship.id].action == "pass"


def test_boarding_targets_contact_and_subsystem_without_blip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui = FakeTerminalUI(choices=["enemy-contact", "engines"])
    controller = _controller(ui)
    ship = controller.session.state.ships[controller._alive_player_ids()[0]]
    target = controller.session.state.ships[controller.session.enemy_runtime_ids[0]]
    target.id = "enemy-contact"
    controller.session.state.ships[target.id] = target
    contacts = [
        ContactInfo(
            target,
            DetectionLevel.CONTACT,
            20,
            0,
            target.position,
            "Escort-class",
            True,
            True,
        ),
        ContactInfo(
            controller.session.state.ships[controller.session.enemy_runtime_ids[1]],
            DetectionLevel.BLIP,
            80,
            10,
            Vector2D(1, 1),
            "Unknown contact",
            False,
            False,
        ),
    ]
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: contacts)

    command = controller._boarding_menu(ship)

    assert command == Command(
        ship.id, "strike", {"target": "enemy-contact", "subsystem": "engines"}
    )
    assert [option.label for option in ui.choose_calls[0][1]] == ["Escort-class"]


def test_concentrated_fire_offers_visible_hostile_and_alive_friendlies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller(FakeTerminalUI(choices=[]))
    state = controller.session.state
    own_ids = controller._alive_player_ids()
    hostile = state.ships[controller.session.enemy_runtime_ids[0]]
    friendly = state.ships[own_ids[1]]
    contacts = [
        ContactInfo(
            hostile,
            DetectionLevel.CONTACT,
            20,
            0,
            hostile.position,
            "Escort-class",
            True,
            True,
        ),
        ContactInfo(
            friendly,
            DetectionLevel.IDENTIFIED,
            5,
            0,
            friendly.position,
            friendly.name,
            False,
            False,
            True,
        ),
    ]
    monkeypatch.setattr(controller.renderer, "preview_contacts", lambda *_args: contacts)
    ui = FakeTerminalUI(choices=[friendly.id])
    controller.ui = ui

    order = controller._ability_order("concentrated_fire")

    assert order is not None
    assert order.target_ship_id == friendly.id
    labels = [option.label for option in ui.choose_calls[0][1]]
    assert "Escort-class" in labels
    assert friendly.name in labels


def test_preview_rendering_never_changes_rng_state() -> None:
    session = build_battle(campaign_state())
    state = session.state
    ship = state.ships[state.player_ships[session.player_id][0]]
    target = state.ships[session.enemy_runtime_ids[0]]
    target.position = Vector2D(
        ship.position.x,
        ship.position.y + ship.hull.sensor_range * 1.2,
    )
    for enemy_id in session.enemy_runtime_ids[1:]:
        state.ships[enemy_id].position = Vector2D(10_000, 10_000)
    renderer = ServerRenderer()
    before = deepcopy(state.dice._rng.getstate())

    for _ in range(3):
        renderer.preview_contacts(ship, state, session.player_id)
        renderer.preview_ship_brief(ship, state, session.player_id)
        renderer.preview_query(session.player_id, ship, "scan", state)
        scanner = renderer.preview_scanner(
            ship,
            state,
            session.player_id,
            grid_width=15,
            grid_height=9,
        )

    assert state.dice._rng.getstate() == before
    assert "SCANNER" in scanner
    assert scanner.count("│") == 18

    renderer.render_ship_brief(ship, state, session.player_id)
    assert state.dice._rng.getstate() != before


def test_contact_preview_hides_runtime_id_and_identity_until_identified() -> None:
    session = build_battle(campaign_state())
    state = session.state
    observer = state.ships[state.player_ships[session.player_id][0]]
    target = state.ships[session.enemy_runtime_ids[0]]
    target.position = Vector2D(
        observer.position.x,
        observer.position.y + observer.hull.sensor_range * 0.9,
    )
    for enemy_id in session.enemy_runtime_ids[1:]:
        state.ships[enemy_id].position = Vector2D(10_000, 10_000)
    renderer = ServerRenderer()

    contact_preview = renderer.preview_ship_brief(observer, state, session.player_id)

    assert "[CONTACT]" in contact_preview
    assert target.id not in contact_preview
    assert target.name not in contact_preview

    target.position = Vector2D(
        observer.position.x,
        observer.position.y + observer.hull.sensor_range * 0.5,
    )
    identified_preview = renderer.preview_query(session.player_id, observer, "scan", state)
    assert target.name in identified_preview
    assert target.id not in identified_preview


def test_compact_scanner_prioritizes_hostiles_and_marks_overflow() -> None:
    session = build_battle(campaign_state())
    state = session.state
    observer = state.ships[state.player_ships[session.player_id][0]]
    hostile = state.ships[session.enemy_runtime_ids[0]]
    hostile.position = Vector2D(observer.position.x, observer.position.y + 10)
    state.ships[session.enemy_runtime_ids[1]].position = Vector2D(
        observer.position.x + 10, observer.position.y
    )
    contacts = ServerRenderer().preview_contacts(observer, state, session.player_id)

    scanner = format_radar_view(
        observer,
        [contact.ship for contact in contacts],
        contact_infos=contacts,
        grid_width=15,
        grid_height=5,
        compact_legend=True,
        legend_limit=2,
    )

    assert hostile.name in scanner
    assert "brg 0° rel" in scanner
    assert "Test Escort" not in scanner
    assert "… 2 more contact(s)" in scanner


def test_teleport_collects_finite_coordinates_and_cancellation() -> None:
    controller = _controller(FakeTerminalUI(texts=["12.5", "-4"]))

    order = controller._ability_order("micro_warp_jump")

    assert order == AbilityOrder(
        fleet_id="player",
        ability_id="micro_warp_jump",
        target_position=Vector2D(12.5, -4.0),
    )

    controller.ui = FakeTerminalUI(texts=[None])
    assert controller._ability_order("micro_warp_jump") is None


def test_warp_rift_collects_position_from_area_effect_steps() -> None:
    controller = LocalBattleController(
        build_battle(campaign_state(Faction.CHAOS_FLEET)),
        ui=FakeTerminalUI(texts=["25", "-10"]),
    )

    order = controller._ability_order("warp_rift")

    assert order == AbilityOrder(
        fleet_id="player",
        ability_id="warp_rift",
        target_position=Vector2D(25, -10),
    )


def test_review_navigation_resolves_once_only_after_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        local_battle,
        "resolve_turn",
        lambda *args: calls.append(args) or TurnLog(turn=0),
    )
    ui = FakeTerminalUI(
        choices=[
            "wait",
            "wait",
            "ability:none",
            None,
            "revise",
            "wait",
            "wait",
            "ability:none",
            "confirm",
        ]
    )
    controller = LocalBattleController(build_battle(campaign_state()), ui=ui, turn_limit=1)

    assert controller.run() is BattleOutcome.TURN_LIMIT
    assert len(calls) == 1
    assert controller.session.state.turn == 1


def test_revise_discards_stance_and_ability_then_confirm_applies_new_pending_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = build_battle(campaign_state())
    player_ids = session.state.player_ships[session.player_id]
    commander = session.state.fleets[session.player_id].commander
    assert commander is not None
    initial_charges = commander.ability_state["concentrated_fire"].remaining_charges
    seen: list[tuple[Stance, int, AbilityOrder | None]] = []

    def resolve_once(state, commands, ability_orders):  # type: ignore[no-untyped-def]
        seen.append(
            (
                state.ships[player_ids[0]].stance,
                commander.ability_state["concentrated_fire"].remaining_charges,
                ability_orders.get("player"),
            )
        )
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    ui = FakeTerminalUI(
        choices=[
            "tactic",
            "stance",
            "lock_on",
            "back",
            "wait",
            "wait",
            "ability:concentrated_fire",
            player_ids[1],
            "revise",
            "tactic",
            "status",
            None,
            "tactic",
            "stance",
            "lock_on",
            "back",
            "wait",
            "wait",
            "ability:concentrated_fire",
            player_ids[0],
            "confirm",
        ]
    )
    controller = LocalBattleController(session, ui=ui, turn_limit=1)

    assert controller.run() is BattleOutcome.TURN_LIMIT
    assert seen == [
        (
            Stance.LOCK_ON,
            initial_charges,
            AbilityOrder("player", "concentrated_fire", target_ship_id=player_ids[0]),
        )
    ]


def test_review_is_human_readable_and_complete() -> None:
    controller = _controller(FakeTerminalUI())
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    target = state.ships[controller.session.enemy_runtime_ids[0]]
    pending = _PendingTurn(
        commands={ship.id: Command(ship.id, "fire", {"slot": 3, "bearing": 17.0})},
        stances={ship.id: Stance.LOCK_ON},
        ability=AbilityOrder("player", "concentrated_fire", target_ship_id=target.id),
    )

    text = controller._format_pending(pending)

    assert ship.name in text
    assert ship.weapons[2].weapon.name in text
    assert "17°" in text
    assert "Lock On" in text
    assert "Concentrated Fire" in text
    assert target.id not in text


def test_review_formats_every_salvo_weapon_and_relative_bearing() -> None:
    controller = _controller(FakeTerminalUI())
    state = controller.session.state
    ship = state.ships[controller._alive_player_ids()[0]]
    pending = _PendingTurn(
        commands={
            ship.id: Command(
                ship.id,
                "fire",
                {
                    "shots": [
                        {"slot": 1, "bearing": 270.0},
                        {"slot": 2, "bearing": 90.0},
                    ]
                },
            )
        }
    )

    text = controller._format_pending(pending)

    assert ship.weapons[0].display_name in text
    assert "bearing 270° rel" in text
    assert ship.weapons[1].display_name in text
    assert "bearing 90° rel" in text


@pytest.mark.parametrize(
    ("choice", "confirmation", "outcome"),
    [
        ("surrender", True, BattleOutcome.SURRENDER),
        ("exit", True, BattleOutcome.ABANDONED),
    ],
)
def test_explicit_exit_choices_require_confirmation_without_resolution(
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    confirmation: bool,
    outcome: BattleOutcome,
) -> None:
    monkeypatch.setattr(
        local_battle,
        "resolve_turn",
        lambda *_args: pytest.fail("turn resolved before confirmation"),
    )
    ui = FakeTerminalUI(
        choices=["wait", "wait", "ability:none", choice],
        confirmations=[confirmation],
    )
    controller = _controller(ui)

    assert controller.run() is outcome
    assert controller.session.state.turn == 0


def test_rejected_exit_confirmation_keeps_pending_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Command]] = []

    def resolve_once(state, commands, ability_orders):  # type: ignore[no-untyped-def]
        seen.append(commands)
        return TurnLog(turn=state.turn)

    monkeypatch.setattr(local_battle, "resolve_turn", resolve_once)
    ui = FakeTerminalUI(
        choices=["wait", "wait", "ability:none", "exit", "confirm"],
        confirmations=[False],
    )
    controller = LocalBattleController(build_battle(campaign_state()), ui=ui, turn_limit=1)

    assert controller.run() is BattleOutcome.TURN_LIMIT
    assert all(seen[0][ship_id].action == "pass" for ship_id in controller._alive_player_ids())


def test_terminal_closed_abandons_without_resolving() -> None:
    class ClosedUI(FakeTerminalUI):
        def choose(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise TerminalClosed

    campaign = campaign_state()
    before = deepcopy(campaign)
    outcome = LocalBattleController(build_battle(campaign), ui=ClosedUI()).run()
    assert outcome is BattleOutcome.ABANDONED
    assert campaign == before


def test_cooldown_one_ability_remains_available_before_tick() -> None:
    controller = _controller(FakeTerminalUI(choices=["ability:concentrated_fire", "player_ship_1"]))
    commander = controller.session.state.fleets["player"].commander
    assert commander is not None
    commander.ability_state["concentrated_fire"] = AbilityState(1, cooldown_remaining=1)

    order = controller._collect_ability()

    assert isinstance(order, AbilityOrder)
    assert order.target_ship_id == "player_ship_1"
