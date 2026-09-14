"""Priority-aware, bounded Telegram transport scheduler."""

from __future__ import annotations

import asyncio
import heapq
import math
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

NORMAL = "NORMAL"
PRESSURE = "PRESSURE"
THROTTLED = "THROTTLED"
COOLDOWN = "COOLDOWN"
PROBE = "PROBE"


@dataclass(order=True, slots=True)
class _QueuedCall:
    priority: int
    sequence: int
    method: str = field(compare=False)
    peer_key: str | None = field(compare=False)
    operation_class: str = field(compare=False)
    operation: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future[Any] = field(compare=False)


@dataclass(slots=True)
class _GovernorScope:
    state: str = NORMAL
    pressure: int = 0
    cooldown_until: float = 0.0


class AdaptiveTelegramGovernor:
    """Learn pressure from actual Telegram wait responses at three scopes."""

    def __init__(self) -> None:
        self._scopes: dict[str, _GovernorScope] = {}

    def _scope(self, key: str) -> _GovernorScope:
        return self._scopes.setdefault(key, _GovernorScope())

    def _refresh(self, scope: _GovernorScope, now: float) -> None:
        if scope.state == COOLDOWN and now >= scope.cooldown_until:
            scope.state = PROBE
            scope.cooldown_until = 0.0

    def observe_wait(
        self,
        method: str,
        seconds: float,
        *,
        peer_key: str | None = None,
        event: str = "flood_wait",
    ) -> None:
        seconds = max(0.0, float(seconds))
        if seconds <= 0:
            return
        now = time.monotonic()
        keys = ["account", f"method:{method}"]
        if peer_key is not None:
            keys.append(f"peer:{peer_key}")
        for key in keys:
            scope = self._scope(key)
            self._refresh(scope, now)
            scope.pressure = min(8, scope.pressure + 1)
            scope.cooldown_until = max(scope.cooldown_until, now + seconds)
            if scope.pressure >= 4:
                scope.state = COOLDOWN
            elif scope.pressure >= 2:
                scope.state = THROTTLED
            else:
                scope.state = PRESSURE
        # Keep the event classification observable without persisting payloads.
        event_key = f"event:{event}"
        event_scope = self._scope(event_key)
        event_scope.pressure = min(8, event_scope.pressure + 1)

    def observe_success(self, method: str, *, peer_key: str | None = None) -> None:
        now = time.monotonic()
        keys = ["account", f"method:{method}"]
        if peer_key is not None:
            keys.append(f"peer:{peer_key}")
        for key in keys:
            scope = self._scope(key)
            self._refresh(scope, now)
            if scope.state == PROBE:
                scope.state = NORMAL
                scope.pressure = max(0, scope.pressure - 2)
            elif scope.state in {PRESSURE, THROTTLED}:
                scope.pressure = max(0, scope.pressure - 1)
                if scope.pressure == 0:
                    scope.state = NORMAL
                elif scope.pressure == 1:
                    scope.state = PRESSURE

    def can_admit(self, method: str, *, peer_key: str | None = None) -> bool:
        now = time.monotonic()
        for key in (f"method:{method}", f"peer:{peer_key}" if peer_key is not None else None):
            if key is None:
                continue
            scope = self._scope(key)
            self._refresh(scope, now)
            if scope.state == COOLDOWN and now < scope.cooldown_until:
                return False
        return True

    def concurrency_limit(self, configured: int) -> int:
        scope = self._scope("account")
        self._refresh(scope, time.monotonic())
        if scope.state == COOLDOWN:
            return 1
        if scope.state == THROTTLED:
            return max(1, math.ceil(configured / 2))
        if scope.state == PRESSURE:
            return max(1, configured - 1)
        if scope.state == PROBE:
            return 1
        return configured

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        result: dict[str, Any] = {}
        for key, scope in self._scopes.items():
            self._refresh(scope, now)
            result[key] = {
                "state": scope.state,
                "pressure": scope.pressure,
                "cooldown_seconds": max(0.0, scope.cooldown_until - now),
            }
        return result


class TelegramTrafficController:
    """Centralize Telegram concurrency, priority and adaptive pressure control."""

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
        self.governor = AdaptiveTelegramGovernor()

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
        self._record_wait(method, seconds, peer_key=peer_key, event="flood_wait")

    def record_slow_mode(
        self, method: str, seconds: float, *, peer_key: str | None = None
    ) -> None:
        self._record_wait(method, seconds, peer_key=peer_key, event="slow_mode")

    def _record_wait(
        self,
        method: str,
        seconds: float,
        *,
        peer_key: str | None,
        event: str,
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
        self.governor.observe_wait(method, seconds, peer_key=peer_key, event=event)
        self._counters[event] += 1

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
            "effective_concurrency": self.governor.concurrency_limit(self.max_concurrency),
            "per_method_limit": self.per_method_limit,
            "per_peer_limit": self.per_peer_limit,
            "max_queue": self.max_queue,
            "method_active": dict(self._method_active),
            "peer_active": dict(self._peer_active),
            "cooldowns": cooldowns,
            "governor": self.governor.snapshot(),
            "counters": dict(self._counters),
        }

    def _eligible(self, item: _QueuedCall, now: float) -> bool:
        if self._method_active[item.method] >= self.per_method_limit:
            return False
        if item.peer_key is not None and self._peer_active[item.peer_key] >= self.per_peer_limit:
            return False
        if not self.governor.can_admit(item.method, peer_key=item.peer_key):
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
                    self._active >= self.governor.concurrency_limit(self.max_concurrency)
                    or not self._queue
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
            self.governor.observe_success(item.method, peer_key=item.peer_key)
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
