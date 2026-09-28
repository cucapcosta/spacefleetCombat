"""Contact formatting and renderer previews used by the online text client."""

from __future__ import annotations

from copy import deepcopy

import pytest

from spacefleet.campaign.battle import build_battle
from spacefleet.cli.display import format_contact, format_radar_view
from spacefleet.core.types import DetectionLevel, Vector2D
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.spatial.detection import ContactInfo
from tests.campaign_helpers import campaign_state


@pytest.mark.parametrize("level", [DetectionLevel.CONTACT, DetectionLevel.IDENTIFIED])
def test_targetable_sensor_contact_shows_runtime_target_id(level: DetectionLevel) -> None:
    session = build_battle(campaign_state())
    observer = session.state.ships[session.state.player_ships[session.player_id][0]]
    target = session.state.ships[session.enemy_runtime_ids[0]]
    contact = ContactInfo(
        ship=target,
        detection_level=level,
        true_distance=20.0,
        true_bearing=0.0,
        display_position=target.position,
        display_name="Escort-class" if level is DetectionLevel.CONTACT else target.name,
        targetable=True,
        accuracy_penalty=level is DetectionLevel.CONTACT,
    )
    assert f"id={target.id}" in format_contact(target, observer, contact_info=contact)


def test_blip_contact_does_not_reveal_runtime_id_or_identity() -> None:
    session = build_battle(campaign_state())
    observer = session.state.ships[session.state.player_ships[session.player_id][0]]
    target = session.state.ships[session.enemy_runtime_ids[0]]
    contact = ContactInfo(
        ship=target,
        detection_level=DetectionLevel.BLIP,
        true_distance=100.0,
        true_bearing=0.0,
        display_position=Vector2D(0.0, 100.0),
        display_name="Unknown contact",
        targetable=False,
        accuracy_penalty=False,
    )
    rendered = format_contact(target, observer, contact_info=contact)
    assert target.id not in rendered
    assert target.name not in rendered
    assert "Unknown contact" in rendered


def test_ship_brief_does_not_reveal_undetected_enemy_id() -> None:
    session = build_battle(campaign_state())
    observer = session.state.ships[session.state.player_ships[session.player_id][0]]
    for enemy_id in session.enemy_runtime_ids:
        session.state.ships[enemy_id].position = Vector2D(10_000.0, 10_000.0)
    rendered = ServerRenderer().preview_ship_brief(observer, session.state, session.player_id)
    assert all(enemy_id not in rendered for enemy_id in session.enemy_runtime_ids)


def test_preview_rendering_never_changes_rng_state() -> None:
    session = build_battle(campaign_state())
    state = session.state
    ship = state.ships[state.player_ships[session.player_id][0]]
    target = state.ships[session.enemy_runtime_ids[0]]
    target.position = Vector2D(ship.position.x, ship.position.y + ship.hull.sensor_range * 1.2)
    for enemy_id in session.enemy_runtime_ids[1:]:
        state.ships[enemy_id].position = Vector2D(10_000, 10_000)
    renderer = ServerRenderer()
    before = deepcopy(state.dice._rng.getstate())

    for _ in range(3):
        renderer.preview_contacts(ship, state, session.player_id)
        renderer.preview_ship_brief(ship, state, session.player_id)
        renderer.preview_query(session.player_id, ship, "scan", state)
        scanner = renderer.preview_scanner(
            ship, state, session.player_id, grid_width=15, grid_height=9
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
        observer.position.x, observer.position.y + observer.hull.sensor_range * 0.9
    )
    for enemy_id in session.enemy_runtime_ids[1:]:
        state.ships[enemy_id].position = Vector2D(10_000, 10_000)
    renderer = ServerRenderer()

    contact_preview = renderer.preview_ship_brief(observer, state, session.player_id)

    assert "[CONTACT]" in contact_preview
    assert target.id not in contact_preview
    assert target.name not in contact_preview

    target.position = Vector2D(
        observer.position.x, observer.position.y + observer.hull.sensor_range * 0.5
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
