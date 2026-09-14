"""Priority-aware, bounded Telegram transport scheduler."""

from __future__ import annotations

import asyncio
import heapq
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.errors import ResourceError


# Lower numeric value means higher priority.
P0_OWNER = 0
P1_INTERACTIVE = 1
P2_NORMAL = 2
P3_BACKGROUND = 3
P4_INDEXING = 4
P5_MAINTENANCE = 5

READ = "READ"
WRITE = "WRITE"
DESTRUCTIVE = "DESTRUCTIVE"
MEDIA = "MEDIA"
DISCOVERY = "DISCOVERY"
BULK = "BULK"
INTERACTIVE = "INTERACTIVE"
RECOVERY = "RECOVERY"


@dataclass(order=True, slots=True)
class _QueuedCall:
    priority: int
    sequence: int
    method: str = field(compare=False)
    peer_key: str | None = field(compare=False)
    operation_class: str = field(compare=False)
    operation: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future[Any] = field(compare=False)


class TelegramTrafficController:
    """Centralize Telegram concurrency, priority and per-key pressure control."""

    def __init__(
        self,
        *,
        max_concurrency: int = 8,
        per_method_limit: int = 4,
        per_peer_limit: int = 2,
        max_queue: int = 512,
    ) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self.per_method_limit = max(1, int(per_method_limit))
        self.per_peer_limit = max(1, int(per_peer_limit))
        self.max_queue = max(1, int(max_queue))
        self._queue: list[_QueuedCall] = []
        self._condition = asyncio.Condition()
        self._dispatcher: asyncio.Task[None] | None = None
        self._running: set[asyncio.Task[None]] = set()
        self._future_tasks: dict[asyncio.Future[Any], asyncio.Task[None]] = {}
        self._closed = False
        self._sequence = 0
        self._active = 0
        self._method_active: Counter[str] = Counter()
        self._peer_active: Counter[str] = Counter()
        self._cooldowns: dict[str, float] = {}
        self._counters: Counter[str] = Counter()

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("Telegram traffic controller is closed")
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(
                self._dispatch_loop(), name="astra-telegram-traffic"
            )

    async def close(self) -> None:
        self._closed = True
        async with self._condition:
            queued = list(self._queue)
            self._queue.clear()
            self._condition.notify_all()
        for item in queued:
            if not item.future.done():
                item.future.cancel()
        if self._dispatcher is not None:
            self._dispatcher.cancel()
            try:
                await self._dispatcher
            except asyncio.CancelledError:
                pass
            self._dispatcher = None
        running = list(self._running)
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        self._running.clear()
        self._future_tasks.clear()

    async def execute(
        self,
        method: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        peer_key: str | None = None,
        operation_class: str = READ,
        priority: int = P2_NORMAL,
    ) -> Any:
        if self._closed:
            raise RuntimeError("Telegram traffic controller is closed")
        await self.start()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        async with self._condition:
            if len(self._queue) >= self.max_queue:
                self._counters["queue_rejected"] += 1
                raise ResourceError("Telegram operation queue is full.")
            self._sequence += 1
            heapq.heappush(
                self._queue,
                _QueuedCall(
                    int(priority),
                    self._sequence,
                    str(method),
                    None if peer_key is None else str(peer_key),
                    str(operation_class),
                    operation,
                    future,
                ),
            )
            self._counters["queued"] += 1
            self._condition.notify_all()
        try:
            return await future
        except asyncio.CancelledError:
            async with self._condition:
                task = self._future_tasks.get(future)
                if task is not None:
                    task.cancel()
                if not future.done():
                    future.cancel()
                self._condition.notify_all()
            raise

    def record_flood_wait(
        self, method: str, seconds: float, *, peer_key: str | None = None
    ) -> None:
        seconds = max(0.0, float(seconds))
        if seconds <= 0:
            return
        until = time.monotonic() + seconds
        keys = [f"method:{method}"]
        if peer_key is not None:
            keys.append(f"peer:{peer_key}")
        for key in keys:
            self._cooldowns[key] = max(self._cooldowns.get(key, 0.0), until)
        self._counters["flood_waits"] += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        cooldowns = {
            key: max(0.0, deadline - now)
            for key, deadline in self._cooldowns.items()
            if deadline > now
        }
        return {
            "queued": len(self._queue),
            "active": self._active,
            "max_concurrency": self.max_concurrency,
            "per_method_limit": self.per_method_limit,
            "per_peer_limit": self.per_peer_limit,
            "max_queue": self.max_queue,
            "method_active": dict(self._method_active),
            "peer_active": dict(self._peer_active),
            "cooldowns": cooldowns,
            "counters": dict(self._counters),
        }

    def _eligible(self, item: _QueuedCall, now: float) -> bool:
        if self._method_active[item.method] >= self.per_method_limit:
            return False
        if item.peer_key is not None and self._peer_active[item.peer_key] >= self.per_peer_limit:
            return False
        if now < self._cooldowns.get(f"method:{item.method}", 0.0):
            return False
        if item.peer_key is not None and now < self._cooldowns.get(
            f"peer:{item.peer_key}", 0.0
        ):
            return False
        return True

    def _pop_eligible(self) -> _QueuedCall | None:
        now = time.monotonic()
        for index, item in enumerate(self._queue):
            if not self._eligible(item, now):
                continue
            selected = self._queue[index]
            last = self._queue.pop()
            if index < len(self._queue):
                self._queue[index] = last
                heapq.heapify(self._queue)
            return selected
        return None

    async def _dispatch_loop(self) -> None:
        while not self._closed:
            async with self._condition:
                while not self._closed and (
                    self._active >= self.max_concurrency or not self._queue
                ):
                    await self._condition.wait()
                if self._closed:
                    return
                item = self._pop_eligible()
                if item is None:
                    cooldown_wait = 0.01
                else:
                    cooldown_wait = None
                    self._active += 1
                    self._method_active[item.method] += 1
                    if item.peer_key is not None:
                        self._peer_active[item.peer_key] += 1
            if cooldown_wait is not None:
                await asyncio.sleep(cooldown_wait)
                continue
            task = asyncio.create_task(self._run(item))
            self._running.add(task)
            self._future_tasks[item.future] = task
            task.add_done_callback(self._task_done)

    async def _run(self, item: _QueuedCall) -> None:
        try:
            if item.future.cancelled():
                return
            result = await item.operation()
            if not item.future.done():
                item.future.set_result(result)
            self._counters["completed"] += 1
        except asyncio.CancelledError:
            if not item.future.done():
                item.future.cancel()
            raise
        except BaseException as exc:
            if not item.future.done():
                item.future.set_exception(exc)
            self._counters["failed"] += 1
        finally:
            async with self._condition:
                self._active = max(0, self._active - 1)
                self._method_active[item.method] -= 1
                if item.peer_key is not None:
                    self._peer_active[item.peer_key] -= 1
                self._condition.notify_all()

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        for future, mapped in tuple(self._future_tasks.items()):
            if mapped is task:
                self._future_tasks.pop(future, None)
                break
