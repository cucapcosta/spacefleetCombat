"""Smoke tests for the real prompt-toolkit UI over a pseudo-terminal."""

from __future__ import annotations

import errno
import os
import select
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

fcntl = pytest.importorskip("fcntl", reason="PTY smoke requires POSIX")
termios = pytest.importorskip("termios", reason="PTY smoke requires POSIX")

_ROOT = Path(__file__).resolve().parents[1]
_ARROW_DOWN = b"\x1b[B"
_ENTER = b"\r"
_ESCAPE = b"\x1b"


def _resize(fd: int, *, columns: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def _read_until(
    fd: int,
    marker: str,
    *,
    timeout: float = 8.0,
    transcript: bytearray | None = None,
) -> str:
    deadline = time.monotonic() + timeout
    received = bytearray()
    expected = marker.encode()
    while expected not in received:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            tail = received[-2000:].decode(errors="replace")
            pytest.fail(f"Timed out waiting for {marker!r}. PTY tail:\n{tail}")
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        received.extend(chunk)
        if transcript is not None:
            transcript.extend(chunk)
    if expected not in received:
        tail = received[-2000:].decode(errors="replace")
        pytest.fail(f"PTY closed before {marker!r}. PTY tail:\n{tail}")
    return received.decode(errors="replace")


def test_real_terminal_main_builder_cancel_and_quit() -> None:
    master_fd, slave_fd = os.openpty()
    process: subprocess.Popen[bytes] | None = None
    transcript = bytearray()
    try:
        _resize(slave_fd, columns=100, rows=30)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["PYTHONPATH"] = str(_ROOT / "src")
        process = subprocess.Popen(
            [sys.executable, "-m", "spacefleet"],
            cwd=_ROOT,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1

        _read_until(master_fd, "Quit", transcript=transcript)
        os.write(master_fd, _ARROW_DOWN * 2 + _ENTER)
        _read_until(master_fd, "Fleet faction", transcript=transcript)
        os.write(master_fd, _ENTER)
        _read_until(master_fd, "Points budget", transcript=transcript)
        os.write(master_fd, _ENTER)
        _read_until(master_fd, "Fleet name", transcript=transcript)
        os.write(master_fd, _ENTER)
        _read_until(master_fd, "No ships in draft.", transcript=transcript)

        os.write(master_fd, _ESCAPE)
        _read_until(master_fd, "Discard this fleet draft?", transcript=transcript)
        _resize(master_fd, columns=60, rows=24)
        os.kill(process.pid, signal.SIGWINCH)
        os.write(master_fd, b"2")

        _read_until(master_fd, "Quit", transcript=transcript)
        os.write(master_fd, _ARROW_DOWN * 4 + _ENTER)
        _read_until(master_fd, "Emperor protects", transcript=transcript)
        assert process.wait(timeout=8) == 0
        assert transcript.count(b"\x1b[?1049h") == 1
        assert transcript.count(b"\x1b[?1049l") == 1
    finally:
        if slave_fd >= 0:
            os.close(slave_fd)
        os.close(master_fd)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
