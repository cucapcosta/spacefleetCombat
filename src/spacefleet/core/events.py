"""Lightweight typed event bus for in-game notifications.

Phases publish events; CLI/UI/AI layers subscribe.  No external deps.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

EventT = TypeVar("EventT", bound="Event")


@dataclass
class Event:
    """Base class for all in-game events."""


Handler = Callable[[EventT], None]


class EventBus:
    """Class-based pub/sub bus.

    Subscribers register a handler for a specific :class:`Event`
    subclass; ``publish`` dispatches to handlers whose registered
    type matches the event's runtime class exactly.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler[Event]]] = {}

    def subscribe(
        self,
        event_type: type[EventT],
        handler: Handler[EventT],
    ) -> None:
        bucket = self._handlers.setdefault(event_type, [])
        bucket.append(handler)  # type: ignore[arg-type]

    def unsubscribe(
        self,
        event_type: type[EventT],
        handler: Handler[EventT],
    ) -> None:
        bucket = self._handlers.get(event_type)
        if not bucket:
            return
        with contextlib.suppress(ValueError):
            bucket.remove(handler)  # type: ignore[arg-type]

    def publish(self, event: Event) -> None:
        for handler in list(self._handlers.get(type(event), [])):
            handler(event)
