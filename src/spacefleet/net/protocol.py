"""Wire protocol — newline-delimited JSON over TCP.

Each message is a single JSON object terminated by ``\\n``.
Uses only the Python standard library (no extra dependencies).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

ENCODING = "utf-8"
SEPARATOR = b"\n"
MAX_LINE = 1024 * 64  # 64 KiB per message — generous for ANSI text

# ── Message type constants ────────────────────────────────────

# Client → Server
MSG_AUTH = "auth"
MSG_COMMAND = "command"
MSG_QUERY = "query"
MSG_READY = "ready"

# Server → Client
MSG_AUTH_OK = "auth_ok"
MSG_AUTH_FAIL = "auth_fail"
MSG_DISPLAY = "display"
MSG_PROMPT = "prompt"
MSG_QUERY_RESULT = "query_result"
MSG_COMMAND_ACK = "command_ack"
MSG_COMMAND_REJECT = "command_reject"
MSG_TURN_RESULT = "turn_result"
MSG_WAITING = "waiting"
MSG_GAME_OVER = "game_over"
MSG_ERROR = "error"


# ── Encode / Decode ──────────────────────────────────────────


def encode_message(msg: dict[str, Any]) -> bytes:
    """Serialize a message dict to wire format (JSON + newline)."""
    return json.dumps(msg, separators=(",", ":")).encode(ENCODING) + SEPARATOR


def decode_message(data: bytes) -> dict[str, Any] | None:
    """Decode a single wire-format message.  Returns *None* on failure."""
    try:
        return json.loads(data.decode(ENCODING))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read one newline-delimited JSON message.  Returns *None* on EOF."""
    try:
        line = await reader.readline()
        if not line:
            return None
        return json.loads(line.decode(ENCODING))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, UnicodeDecodeError, ConnectionResetError):
        return None


async def write_message(
    writer: asyncio.StreamWriter,
    msg: dict[str, Any],
) -> None:
    """Write one JSON message to the stream and drain."""
    writer.write(encode_message(msg))
    await writer.drain()
