"""WSSession against a scripted in-process aiohttp websocket server."""

from __future__ import annotations

import asyncio
import json
import socket
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web

from spacefleet.net.ws_session import SessionEvent, WSSession

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _prompt() -> dict[str, Any]:
    return {"type": "prompt", "ship_id": "s1", "ship_name": "Vengeful", "text": "Orders?"}


async def _game_script(ws: web.WebSocketResponse, received: list[dict[str, Any]]) -> None:
    """auth → display → prompt; answer queries/moves/fire with a re-prompt, pass ends."""
    received.append(json.loads((await ws.receive()).data))
    await ws.send_json(
        {"type": "auth_ok", "message": "Welcome alice", "ship_names": ["Vengeful", "Lance"]}
    )
    await ws.send_json({"type": "display", "text": "\x1b[31mRED\x1b[0m alert"})
    await ws.send_json(_prompt())
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            break
        data = json.loads(msg.data)
        received.append(data)
        if data["type"] == "query":
            await ws.send_json({"type": "query_result", "text": f"result {data['query']}"})
            await ws.send_json(_prompt())
        elif data["action"] == "pass":
            await ws.send_json({"type": "command_ack", "text": "Passed."})
            await ws.send_json({"type": "game_over", "text": "Victory!"})
            break
        elif data["action"] == "fire":
            await ws.send_json({"type": "command_reject", "reason": "Out of arc"})
            await ws.send_json(_prompt())
        else:
            await ws.send_json({"type": "command_ack", "text": "Maneuver held."})
            await ws.send_json(_prompt())
    await ws.close()


async def _auth_fail_script(ws: web.WebSocketResponse, received: list[dict[str, Any]]) -> None:
    received.append(json.loads((await ws.receive()).data))
    await ws.send_json({"type": "auth_fail", "reason": "Game full"})
    await ws.close()


async def _idle_script(ws: web.WebSocketResponse, received: list[dict[str, Any]]) -> None:
    received.append(json.loads((await ws.receive()).data))
    await ws.send_json({"type": "auth_ok", "ship_names": ["Vengeful"]})
    await ws.send_json({"type": "waiting", "text": "  Waiting for other players..."})
    async for _ in ws:
        pass


class Harness:
    def __init__(self, session: WSSession, events: asyncio.Queue[SessionEvent]) -> None:
        self.session = session
        self.events = events
        self.seen: list[SessionEvent] = []

    async def until(self, kind: str) -> SessionEvent:
        while True:
            event = await asyncio.wait_for(self.events.get(), timeout=5)
            self.seen.append(event)
            if event.kind == kind:
                return event


async def _with_server(
    script: Any, body: Callable[[Harness, list[dict[str, Any]]], Awaitable[None]]
) -> None:
    received: list[dict[str, Any]] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await script(ws, received)
        return ws

    app = web.Application()
    app.router.add_get("/ws", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    events: asyncio.Queue[SessionEvent] = asyncio.Queue()
    session = WSSession(f"ws://127.0.0.1:{port}/ws", "alice", events.put_nowait)
    task = asyncio.create_task(session.run())
    try:
        await body(Harness(session, events), received)
        await asyncio.wait_for(task, timeout=5)
    finally:
        task.cancel()
        await runner.cleanup()


def test_session_full_game_flow() -> None:
    async def body(h: Harness, received: list[dict[str, Any]]) -> None:
        prompt = await h.until("prompt")
        assert (prompt.ship_id, prompt.ship_name, prompt.text) == ("s1", "Vengeful", "Orders?")
        assert h.session.awaiting_input
        assert h.session.ship_names == ("Vengeful", "Lance")

        assert "Unknown command" in (await h.session.send_line("bogus") or "")
        assert "Usage: fire" in (await h.session.send_line("fire 1") or "")
        assert "Usage: move" in (await h.session.send_line("move 8 up 30") or "")
        assert await h.session.send_line("   ") is None

        assert await h.session.send_line("move 8 port 30") is None
        assert not h.session.awaiting_input
        assert "Not your turn" in (await h.session.send_line("pass") or "")
        await h.until("prompt")
        assert await h.session.send_line("?") is None
        await h.until("prompt")
        assert await h.session.send_line("stance brace") is None
        await h.until("prompt")
        assert await h.session.send_line("fire 1 270") is None
        await h.until("prompt")
        assert await h.session.send_line("PASS") is None
        over = await h.until("game_over")
        assert over.text == "Victory!"
        await h.until("disconnected")

        assert received == [
            {"type": "auth", "username": "alice"},
            {
                "type": "command",
                "ship_id": "s1",
                "action": "move",
                "args": {},
                "maneuver": {"speed": 8.0, "turn": -30.0},
            },
            {"type": "query", "ship_id": "s1", "query": "help"},
            {"type": "query", "ship_id": "s1", "query": "stance brace"},
            {
                "type": "command",
                "ship_id": "s1",
                "action": "fire",
                "args": {"slot": 1, "bearing": 270.0},
            },
            {"type": "command", "ship_id": "s1", "action": "pass", "args": {}},
        ]
        kinds = [e.kind for e in h.seen]
        assert kinds[0] == "connected"
        texts = [e.text for e in h.seen]
        assert "\x1b[31mRED\x1b[0m alert" in texts
        assert "  Welcome alice\n  Your ships: Vengeful, Lance" in texts
        assert "result help" in texts
        assert "Maneuver held." in texts
        assert "Passed." in texts
        errors = [e.text for e in h.seen if e.kind == "error"]
        assert errors == ["  \x1b[31mRejected:\x1b[0m Out of arc"]
        assert h.seen[-1].kind == "disconnected"

    asyncio.run(_with_server(_game_script, body))


def test_session_auth_fail_reports_reason() -> None:
    async def body(h: Harness, received: list[dict[str, Any]]) -> None:
        error = await h.until("error")
        assert "Authentication failed: Game full" in error.text
        await h.until("disconnected")

    asyncio.run(_with_server(_auth_fail_script, body))


def test_session_close_and_quit_disconnect() -> None:
    async def body(h: Harness, received: list[dict[str, Any]]) -> None:
        waiting = await h.until("text")
        while "Waiting" not in waiting.text:
            waiting = await h.until("text")
        assert "Not your turn" in (await h.session.send_line("status") or "")
        assert await h.session.send_line("quit") is None
        event = await h.until("disconnected")
        assert event.text.strip() == "Disconnected."
        assert "Not connected" in (await h.session.send_line("status") or "")

    asyncio.run(_with_server(_idle_script, body))


def test_session_connection_error() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    events: list[SessionEvent] = []
    session = WSSession(f"ws://127.0.0.1:{port}/ws", "alice", events.append)
    asyncio.run(session.run())
    assert [e.kind for e in events] == ["error", "disconnected"]
    assert "Cannot connect" in events[0].text
