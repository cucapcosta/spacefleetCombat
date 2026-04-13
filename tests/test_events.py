"""Tests for the core event bus."""

from __future__ import annotations

from dataclasses import dataclass

from spacefleet.core.events import Event, EventBus


@dataclass
class HitEvent(Event):
    target: str = ""
    damage: int = 0


def test_subscribe_and_publish():
    bus = EventBus()
    received: list[HitEvent] = []
    bus.subscribe(HitEvent, received.append)
    bus.publish(HitEvent(target="enemy", damage=3))
    assert received == [HitEvent(target="enemy", damage=3)]


def test_multiple_subscribers():
    bus = EventBus()
    a: list[Event] = []
    b: list[Event] = []
    bus.subscribe(HitEvent, a.append)
    bus.subscribe(HitEvent, b.append)
    bus.publish(HitEvent(target="x", damage=1))
    assert len(a) == 1
    assert len(b) == 1


def test_unrelated_events_ignored():
    @dataclass
    class OtherEvent(Event):
        pass

    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(HitEvent, seen.append)
    bus.publish(OtherEvent())
    assert seen == []


def test_unsubscribe():
    bus = EventBus()
    seen: list[Event] = []
    handler = seen.append
    bus.subscribe(HitEvent, handler)
    bus.unsubscribe(HitEvent, handler)
    bus.publish(HitEvent(target="x", damage=1))
    assert seen == []
