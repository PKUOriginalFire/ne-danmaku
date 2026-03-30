"""Custom ASGI runner based on Uvicorn's internal `_serve`.

This runner avoids `uvicorn.run()`'s built-in signal capture so the process
can coordinate multiple ASGI servers (e.g. FastAPI + Quart) consistently.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from types import FrameType

from uvicorn import Config, Server


HANDLED_SIGNALS: tuple[int, ...] = (
    signal.SIGINT,
    signal.SIGTERM,
)
if sys.platform == "win32":  # pragma: no cover
    HANDLED_SIGNALS += (signal.SIGBREAK,)


def _build_exit_handler(server: Server, captured: list[int]) -> Callable[[int, FrameType | None], None]:
    def _handle_exit(sig: int, frame: FrameType | None) -> None:
        _ = frame
        captured.append(sig)
        if server.should_exit and sig == signal.SIGINT:
            server.force_exit = True
        else:
            server.should_exit = True

    return _handle_exit


@contextmanager
def _capture_signals(server: Server):
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    captured: list[int] = []
    handler = _build_exit_handler(server, captured)
    original_handlers = {sig: signal.signal(sig, handler) for sig in HANDLED_SIGNALS}
    try:
        yield
    finally:
        for sig, original in original_handlers.items():
            signal.signal(sig, original)
        for sig in reversed(captured):
            signal.raise_signal(sig)


async def serve_asgi(
    app,
    *,
    host: str,
    port: int,
    log_level: str = "info",
) -> None:
    """Run an ASGI app via `uvicorn.Server._serve` with custom signal logic."""

    config = Config(app=app, host=host, port=port, log_level=log_level)
    server = Server(config)
    with _capture_signals(server):
        await server._serve()


def run_asgi(
    app,
    *,
    host: str,
    port: int,
    log_level: str = "info",
) -> None:
    """Synchronous entrypoint for serving one ASGI app."""

    asyncio.run(
        serve_asgi(
            app,
            host=host,
            port=port,
            log_level=log_level,
        )
    )
