"""A per-process, priority-aware semaphore for model calls (AD-8).

`PSA_MODEL_SLOTS` slots (at most `OLLAMA_NUM_PARALLEL`). Waiting `interactive` callers are
always granted a freed slot before waiting `background` callers; callers of the same
priority are served FIFO. A slot is released on success, error or cancellation, and a
waiter cancelled after being granted a slot passes it on, so slots never leak.

Not thread-safe: use it from one event loop.
"""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import MappingProxyType

from app.platform.jobs.registry import Priority

# Grant order: the first non-empty queue wins.
_ORDER: tuple[Priority, ...] = ("interactive", "background")


class PrioritySemaphore:
    def __init__(self, slots: int) -> None:
        if slots < 1:
            raise ValueError("slots must be >= 1")
        self._slots = slots
        self._free = slots
        self._waiters: Mapping[Priority, deque[asyncio.Future[None]]] = MappingProxyType(
            {priority: deque() for priority in _ORDER}
        )

    @property
    def slots(self) -> int:
        return self._slots

    @property
    def free(self) -> int:
        return self._free

    def waiting(self, priority: Priority | None = None) -> int:
        """Callers still waiting (cancelled ones excluded)."""
        queues = [self._waiters[priority]] if priority else list(self._waiters.values())
        return sum(1 for queue in queues for fut in queue if not fut.done())

    async def acquire(self, priority: Priority) -> None:
        if self._free > 0 and self.waiting() == 0:
            self._free -= 1
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        queue = self._waiters[priority]
        queue.append(fut)
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                # Granted a slot just as we were cancelled: hand it to the next waiter.
                self.release()
            else:
                try:
                    queue.remove(fut)
                except ValueError:
                    pass
            raise

    def release(self) -> None:
        """Give the slot to the next waiter (interactive first, then FIFO), or free it."""
        for priority in _ORDER:
            queue = self._waiters[priority]
            while queue:
                fut = queue.popleft()
                if not fut.done():
                    fut.set_result(None)  # the slot passes straight to this waiter
                    return
        if self._free >= self._slots:
            raise RuntimeError("PrioritySemaphore released more times than acquired")
        self._free += 1

    @asynccontextmanager
    async def slot(self, priority: Priority) -> AsyncIterator[None]:
        await self.acquire(priority)
        try:
            yield
        finally:
            self.release()
