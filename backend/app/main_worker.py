"""`worker` process entry point: jobs only (AD-1, AD-7).

Placeholder until Epic 2 adds the Postgres job queue. It logs a start event and idles until
it receives SIGINT/SIGTERM.
"""

import asyncio
import signal
import sys

from app.platform.config import get_settings
from app.platform.logging import configure_logging, get_logger

_log = get_logger("app.worker")


async def run(stop: asyncio.Event, idle_s: float = 5.0) -> None:
    settings = get_settings()
    _log.info("worker.started", extra={"version": settings.version, "env": settings.env})
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=idle_s)
        except TimeoutError:
            continue  # no-op: job claiming arrives in Epic 2
    _log.info("worker.stopped")


async def _main() -> None:
    stop = asyncio.Event()
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    await run(stop)


def main() -> None:
    configure_logging(get_settings().log_level)
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        _log.info("worker.stopped")


if __name__ == "__main__":
    main()
