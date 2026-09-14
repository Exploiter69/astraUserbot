"""Durable, bounded Telegram entity/dialog state cache."""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True, slots=True)
class EntityState:
    lookup_key: str
    entity_id: int | None
    access_hash: int | None
    username: str | None
    title: str | None
    first_name: str | None
    last_name: str | None
    entity_type: str
    last_seen: float
    photo_id: str | None = None
    capabilities: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DialogState:
    peer_key: str
    dialog_type: str
    title: str | None
    username: str | None
    last_message_id: int | None
    last_sync_at: float
    sync_state: str


class TelegramStateCache:
    """Bounded state cache for Telegram entities and dialogs.

    Durable rows are observations only. In-memory Telegram objects are kept
    separately and are never reconstructed into mutation authority from stale
    SQLite data.
    """

    def __init__(
        self,
        storage: Any,
        *,
        entity_ttl: float = 300.0,
        dialog_ttl: float = 120.0,
        max_entities: int = 5000,
        max_dialogs: int = 2000,
    ) -> None:
        self.storage = storage
        self.entity_ttl = max(0.0, float(entity_ttl))
        self.dialog_ttl = max(0.0, float(dialog_ttl))
        self.max_entities = max(1, int(max_entities))
        self.max_dialogs = max(1, int(max_dialogs))
        self._entities: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._entity_states: OrderedDict[str, EntityState] = OrderedDict()
        self._dialogs: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._dialog_snapshot_at = 0.0
        self._dialog_snapshot_limit = 0
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._lock_guard = asyncio.Lock()
        self._started = False
        self._stats = {
            "entity_hits": 0,
            "entity_misses": 0,
            "dialog_hits": 0,
            "dialog_misses": 0,
            "inflight_joins": 0,
        }

    async def start(self) -> None:
        self._started = True

    async def close(self) -> None:
        self._entities.clear()
        self._entity_states.clear()
        self._dialogs.clear()
        self._dialog_snapshot_at = 0.0
        self._dialog_snapshot_limit = 0
        async with self._lock_guard:
            for future in self._inflight.values():
                if not future.done():
                    future.cancel()
            self._inflight.clear()
        self._started = False

    @staticmethod
    def entity_key(value: Any) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return f"username:{normalized.lstrip('@')}"
        entity_id = getattr(value, "id", None)
        if entity_id is not None:
            return f"id:{entity_id}"
        if isinstance(value, int):
            return f"id:{value}"
        return f"value:{str(value).strip().lower()}"

    @staticmethod
    def peer_key(value: Any) -> str:
        return TelegramStateCache.entity_key(value)

    async def remember_entity(self, lookup: Any, entity: Any, *, capabilities: dict[str, Any] | None = None) -> EntityState:
        key = self.entity_key(lookup)
        now = time.time()
        state = self._entity_state(key, entity, now, capabilities=capabilities)
        self._entities[key] = (now, entity)
        self._entities.move_to_end(key)
        self._entity_states[key] = state
        self._entity_states.move_to_end(key)
        self._trim_memory()
        await self.storage.execute(
            """INSERT INTO telegram_entities
               (lookup_key, entity_id, access_hash, username, title, first_name, last_name,
                entity_type, last_seen, photo_id, capabilities_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(lookup_key) DO UPDATE SET
                 entity_id=excluded.entity_id, access_hash=excluded.access_hash,
                 username=excluded.username, title=excluded.title,
                 first_name=excluded.first_name, last_name=excluded.last_name,
                 entity_type=excluded.entity_type, last_seen=excluded.last_seen,
                 photo_id=excluded.photo_id, capabilities_json=excluded.capabilities_json""",
            (
                state.lookup_key, state.entity_id, state.access_hash, state.username, state.title,
                state.first_name, state.last_name, state.entity_type, state.last_seen,
                state.photo_id, json.dumps(state.capabilities or {}, sort_keys=True),
            ),
        )
        await self._prune_entities()
        return state

    async def get_entity_state(self, lookup: Any, *, fresh: bool = True) -> EntityState | None:
        key = self.entity_key(lookup)
        now = time.time()
        state = self._entity_states.get(key)
        if state is not None:
            age = now - state.last_seen
            if not fresh or age <= self.entity_ttl:
                self._entity_states.move_to_end(key)
                self._stats["entity_hits"] += 1
                return state
        row = await self.storage.fetchone(
            """SELECT lookup_key, entity_id, access_hash, username, title, first_name,
                      last_name, entity_type, last_seen, photo_id, capabilities_json
               FROM telegram_entities WHERE lookup_key=?""",
            (key,),
        )
        if row is None:
            self._stats["entity_misses"] += 1
            return None
        state = EntityState(
            lookup_key=str(row[0]), entity_id=int(row[1]) if row[1] is not None else None,
            access_hash=int(row[2]) if row[2] is not None else None, username=row[3], title=row[4],
            first_name=row[5], last_name=row[6], entity_type=str(row[7]), last_seen=float(row[8]),
            photo_id=row[9], capabilities=json.loads(row[10] or "{}"),
        )
        self._entity_states[key] = state
        self._entity_states.move_to_end(key)
        self._trim_memory()
        if fresh and now - state.last_seen > self.entity_ttl:
            self._stats["entity_misses"] += 1
            return None
        self._stats["entity_hits"] += 1
        return state

    def get_memory_entity(self, lookup: Any) -> Any | None:
        key = self.entity_key(lookup)
        item = self._entities.get(key)
        if item is None:
            return None
        observed, entity = item
        if time.time() - observed > self.entity_ttl:
            self._entities.pop(key, None)
            return None
        self._entities.move_to_end(key)
        return entity

    async def resolve_entity(self, lookup: Any, resolver: Callable[[], Awaitable[Any]]) -> Any:
        cached = self.get_memory_entity(lookup)
        if cached is not None:
            self._stats["entity_hits"] += 1
            return cached

        key = f"entity:{self.entity_key(lookup)}"
        async with self._lock_guard:
            future = self._inflight.get(key)
            owner = future is None
            if owner:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
            else:
                self._stats["inflight_joins"] += 1
        assert future is not None
        if not owner:
            return await asyncio.shield(future)

        self._stats["entity_misses"] += 1
        try:
            entity = await resolver()
            try:
                await self.remember_entity(lookup, entity)
            except Exception:
                pass
            future.set_result(entity)
            return entity
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            async with self._lock_guard:
                self._inflight.pop(key, None)

    async def remember_dialog(self, dialog: Any, *, sync_state: str = "OBSERVED") -> DialogState:
        key = self.peer_key(getattr(dialog, "entity", dialog))
        now = time.time()
        entity = getattr(dialog, "entity", dialog)
        state = DialogState(
            peer_key=key,
            dialog_type=type(entity).__name__,
            title=self._text(getattr(entity, "title", None) or getattr(entity, "first_name", None) or getattr(entity, "last_name", None)),
            username=self._text(getattr(entity, "username", None)),
            last_message_id=self._int(getattr(getattr(dialog, "message", None), "id", None)),
            last_sync_at=now,
            sync_state=sync_state,
        )
        self._dialogs[key] = (now, dialog)
        self._dialogs.move_to_end(key)
        self._trim_memory()
        await self.storage.execute(
            """INSERT INTO telegram_dialogs
               (peer_key, dialog_type, title, username, last_message_id, last_sync_at, sync_state)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(peer_key) DO UPDATE SET
                 dialog_type=excluded.dialog_type, title=excluded.title,
                 username=excluded.username, last_message_id=excluded.last_message_id,
                 last_sync_at=excluded.last_sync_at, sync_state=excluded.sync_state""",
            (state.peer_key, state.dialog_type, state.title, state.username, state.last_message_id, state.last_sync_at, state.sync_state),
        )
        await self._prune_dialogs()
        return state

    def mark_dialog_snapshot(self, *, limit: int | None) -> None:
        self._dialog_snapshot_at = time.time()
        self._dialog_snapshot_limit = max(1, min(limit or self.max_dialogs, self.max_dialogs))

    def memory_dialogs(self, *, limit: int | None = None) -> list[Any] | None:
        requested = max(1, min(limit or self.max_dialogs, self.max_dialogs))
        if self._dialog_snapshot_at <= 0 or requested > self._dialog_snapshot_limit:
            return None
        if time.time() - self._dialog_snapshot_at > self.dialog_ttl:
            return None
        fresh = [(observed, dialog) for observed, dialog in self._dialogs.values() if time.time() - observed <= self.dialog_ttl]
        if len(fresh) < min(requested, self._dialog_snapshot_limit):
            return None
        fresh.sort(key=lambda item: item[0], reverse=True)
        return [dialog for _, dialog in fresh[:requested]]

    async def get_dialog_state(self, peer: Any, *, fresh: bool = True) -> DialogState | None:
        key = self.peer_key(peer)
        item = self._dialogs.get(key)
        now = time.time()
        if item is not None and (not fresh or now - item[0] <= self.dialog_ttl):
            self._dialogs.move_to_end(key)
            self._stats["dialog_hits"] += 1
            dialog = item[1]
            entity = getattr(dialog, "entity", dialog)
            return DialogState(
                peer_key=key, dialog_type=type(entity).__name__,
                title=self._text(getattr(entity, "title", None)), username=self._text(getattr(entity, "username", None)),
                last_message_id=self._int(getattr(getattr(dialog, "message", None), "id", None)),
                last_sync_at=item[0], sync_state="MEMORY",
            )
        row = await self.storage.fetchone(
            """SELECT peer_key, dialog_type, title, username, last_message_id, last_sync_at, sync_state
               FROM telegram_dialogs WHERE peer_key=?""",
            (key,),
        )
        if row is None:
            self._stats["dialog_misses"] += 1
            return None
        state = DialogState(
            peer_key=str(row[0]), dialog_type=str(row[1]), title=row[2], username=row[3],
            last_message_id=int(row[4]) if row[4] is not None else None,
            last_sync_at=float(row[5]), sync_state=str(row[6]),
        )
        if fresh and now - state.last_sync_at > self.dialog_ttl:
            self._stats["dialog_misses"] += 1
            return None
        self._stats["dialog_hits"] += 1
        return state

    async def cached_dialogs(self, *, limit: int | None = None) -> list[DialogState]:
        cap = max(1, min(limit or self.max_dialogs, self.max_dialogs))
        rows = await self.storage.fetchall(
            """SELECT peer_key, dialog_type, title, username, last_message_id, last_sync_at, sync_state
               FROM telegram_dialogs ORDER BY last_sync_at DESC LIMIT ?""",
            (cap,),
        )
        return [
            DialogState(
                peer_key=str(row[0]), dialog_type=str(row[1]), title=row[2], username=row[3],
                last_message_id=int(row[4]) if row[4] is not None else None,
                last_sync_at=float(row[5]), sync_state=str(row[6]),
            )
            for row in rows
        ]

    async def invalidate_entity(self, lookup: Any) -> None:
        key = self.entity_key(lookup)
        self._entities.pop(key, None)
        self._entity_states.pop(key, None)
        await self.storage.execute("DELETE FROM telegram_entities WHERE lookup_key=?", (key,))

    async def invalidate_dialog(self, peer: Any) -> None:
        key = self.peer_key(peer)
        self._dialogs.pop(key, None)
        self._dialog_snapshot_at = 0.0
        self._dialog_snapshot_limit = 0
        await self.storage.execute("DELETE FROM telegram_dialogs WHERE peer_key=?", (key,))

    def snapshot(self) -> dict[str, Any]:
        return {
            "entities_memory": len(self._entities),
            "entity_states_memory": len(self._entity_states),
            "dialogs_memory": len(self._dialogs),
            "dialog_snapshot_limit": self._dialog_snapshot_limit,
            "dialog_snapshot_age": max(0.0, time.time() - self._dialog_snapshot_at) if self._dialog_snapshot_at else None,
            "inflight": len(self._inflight),
            "max_entities": self.max_entities,
            "max_dialogs": self.max_dialogs,
            "entity_ttl": self.entity_ttl,
            "dialog_ttl": self.dialog_ttl,
            **self._stats,
        }

    async def _prune_entities(self) -> None:
        row = await self.storage.fetchone("SELECT COUNT(*) FROM telegram_entities")
        count = int(row[0]) if row else 0
        excess = count - self.max_entities
        if excess > 0:
            await self.storage.execute(
                "DELETE FROM telegram_entities WHERE lookup_key IN (SELECT lookup_key FROM telegram_entities ORDER BY last_seen ASC LIMIT ?)",
                (excess,),
            )

    async def _prune_dialogs(self) -> None:
        row = await self.storage.fetchone("SELECT COUNT(*) FROM telegram_dialogs")
        count = int(row[0]) if row else 0
        excess = count - self.max_dialogs
        if excess > 0:
            await self.storage.execute(
                "DELETE FROM telegram_dialogs WHERE peer_key IN (SELECT peer_key FROM telegram_dialogs ORDER BY last_sync_at ASC LIMIT ?)",
                (excess,),
            )

    def _trim_memory(self) -> None:
        while len(self._entities) > self.max_entities:
            self._entities.popitem(last=False)
        while len(self._entity_states) > self.max_entities:
            self._entity_states.popitem(last=False)
        while len(self._dialogs) > self.max_dialogs:
            self._dialogs.popitem(last=False)

    @staticmethod
    def _entity_state(key: str, entity: Any, now: float, *, capabilities: dict[str, Any] | None) -> EntityState:
        entity_id = TelegramStateCache._int(getattr(entity, "id", None))
        access_hash = TelegramStateCache._int(getattr(entity, "access_hash", None))
        username = TelegramStateCache._text(getattr(entity, "username", None))
        title = TelegramStateCache._text(getattr(entity, "title", None))
        first_name = TelegramStateCache._text(getattr(entity, "first_name", None))
        last_name = TelegramStateCache._text(getattr(entity, "last_name", None))
        photo = getattr(entity, "photo", None)
        photo_id = TelegramStateCache._text(getattr(photo, "photo_id", None))
        return EntityState(
            lookup_key=key, entity_id=entity_id, access_hash=access_hash,
            username=username, title=title, first_name=first_name, last_name=last_name,
            entity_type=type(entity).__name__, last_seen=now, photo_id=photo_id,
            capabilities=capabilities,
        )

    @staticmethod
    def _text(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
