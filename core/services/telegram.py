"""Telegram operation facade with centralized traffic governance and state caching."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from typing import Any

from telethon.errors import FloodWaitError, SlowModeWaitError

from core.errors import ExternalServiceError, TimeoutError
from core.services.telegram_recorder import TelegramOperationRecorder, request_fingerprint
from core.services.telegram_state import TelegramStateCache
from core.services.telegram_traffic import DESTRUCTIVE, DISCOVERY, MEDIA, P1_INTERACTIVE, P2_NORMAL, READ, TelegramTrafficController, WRITE

logger = logging.getLogger("astra.services.telegram")


class TelegramFacade:
    """Centralize common Telegram operations while keeping raw Telethon available."""

    def __init__(self, client: Any, *, flood_wait_cap: float = 60.0, retries: int = 1, max_concurrency: int = 8, per_method_limit: int = 4, per_peer_limit: int = 2, max_queue: int = 512, recorder: TelegramOperationRecorder | None = None, state_cache: TelegramStateCache | None = None) -> None:
        self.client = client
        self.flood_wait_cap = max(0.0, float(flood_wait_cap))
        self.retries = max(0, int(retries))
        self.traffic = TelegramTrafficController(max_concurrency=max_concurrency, per_method_limit=per_method_limit, per_peer_limit=per_peer_limit, max_queue=max_queue)
        self.recorder = recorder
        self.state_cache = state_cache

    async def start(self) -> None:
        await self.traffic.start()

    async def close(self) -> None:
        await self.traffic.close()

    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any:
        return await self._call("send_message", entity, message, operation_class=WRITE, priority=P1_INTERACTIVE, **kwargs)

    async def send_file(self, entity: Any, file: Any, *, caption: str | None = None, **kwargs: Any) -> Any:
        if caption is not None:
            kwargs["caption"] = caption
        return await self._call("send_file", entity, file, operation_class=MEDIA, priority=P2_NORMAL, **kwargs)

    async def edit_message(self, entity: Any, message: Any, text: str, **kwargs: Any) -> Any:
        return await self._call("edit_message", entity, message, text, operation_class=WRITE, priority=P1_INTERACTIVE, **kwargs)

    async def delete_messages(self, entity: Any, message_ids: int | Sequence[int], **kwargs: Any) -> Any:
        return await self._call("delete_messages", entity, message_ids, operation_class=DESTRUCTIVE, priority=P1_INTERACTIVE, **kwargs)

    async def get_messages(self, entity: Any, *, limit: int = 100, min_id: int | None = None, max_id: int | None = None) -> list[Any]:
        bounded = max(1, min(int(limit), 100))
        kwargs: dict[str, Any] = {"limit": bounded}
        if min_id is not None:
            kwargs["min_id"] = int(min_id)
        if max_id is not None:
            kwargs["max_id"] = int(max_id)
        result = await self._call("get_messages", entity, operation_class=READ, priority=P2_NORMAL, **kwargs)
        return list(result or [])

    async def get_entity(self, entity: Any) -> Any:
        if self.state_cache is None:
            return await self._call("get_entity", entity, operation_class=DISCOVERY, priority=P2_NORMAL)
        return await self.state_cache.resolve_entity(entity, lambda: self._call("get_entity", entity, operation_class=DISCOVERY, priority=P2_NORMAL))

    async def get_dialogs(self, *, limit: int | None = None, refresh: bool = False) -> list[Any]:
        if self.state_cache is not None and not refresh:
            cached = self.state_cache.memory_dialogs(limit=limit)
            if cached is not None:
                return cached
        dialogs = await self._call("get_dialogs", limit=limit, operation_class=DISCOVERY, priority=P2_NORMAL)
        if self.state_cache is not None:
            for dialog in dialogs:
                try:
                    await self.state_cache.remember_dialog(dialog)
                except Exception:
                    logger.warning("Telegram dialog cache write failed", exc_info=True)
            self.state_cache.mark_dialog_snapshot(limit=len(dialogs))
        return list(dialogs)

    async def get_capabilities(self, entity: Any, *, fresh: bool = True) -> dict[str, Any]:
        if self.state_cache is not None:
            state = await self.state_cache.get_entity_state(entity, fresh=fresh)
            if state is not None and state.capabilities:
                return dict(state.capabilities)
        resolved = await self.get_entity(entity)
        capabilities: dict[str, Any] = {"can_read": True, "can_send": None, "can_edit": None, "can_delete": None, "can_pin": None, "can_react": None, "slow_mode_seconds": None, "restricted": None, "observed_at": time.time()}
        try:
            permissions = await self._call("get_permissions", resolved, "me", operation_class=DISCOVERY, priority=P2_NORMAL)
            mapping = {"can_send": "send_messages", "can_edit": "edit_messages", "can_delete": "delete_messages", "can_pin": "pin_messages", "can_react": "send_reactions"}
            for capability, attribute in mapping.items():
                value = getattr(permissions, attribute, None)
                if value is not None:
                    capabilities[capability] = bool(value)
        except Exception as exc:
            capabilities["permissions_observation"] = "UNAVAILABLE"
            capabilities["permissions_error"] = type(exc).__name__
        slow_mode = getattr(resolved, "slowmode_seconds", None)
        if slow_mode is None:
            slow_mode = getattr(resolved, "slow_mode_seconds", None)
        if slow_mode is not None:
            capabilities["slow_mode_seconds"] = int(slow_mode)
        restricted = getattr(resolved, "restricted", None)
        if restricted is not None:
            capabilities["restricted"] = bool(restricted)
        if self.state_cache is not None:
            try:
                await self.state_cache.remember_entity(entity, resolved, capabilities=capabilities)
            except Exception:
                logger.warning("Telegram capability cache write failed", exc_info=True)
        return capabilities

    def traffic_snapshot(self) -> dict[str, Any]:
        return self.traffic.snapshot()

    def state_snapshot(self) -> dict[str, Any]:
        return self.state_cache.snapshot() if self.state_cache is not None else {}

    async def _record(self, *, operation_id: str, timestamp: float, started_at: float, method: str, peer_key: str | None, operation_class: str, request_hash: str, payload_size: int, result_classification: str, error_class: str | None = None, retry_count: int = 0, flood_wait_seconds: float | None = None, slow_mode_seconds: float | None = None, peer_flood: bool = False) -> None:
        if self.recorder is None:
            return
        await self.recorder.record(operation_id=operation_id, started_at=timestamp, method=method, peer_id=peer_key, operation_class=operation_class, request_hash=request_hash, result_classification=result_classification, latency_ms=(time.monotonic() - started_at) * 1000.0, error_class=error_class, retry_count=retry_count, flood_wait_seconds=flood_wait_seconds, slow_mode_seconds=slow_mode_seconds, peer_flood=peer_flood, payload_size=payload_size)

    async def _call(self, method: str, *args: Any, operation_class: str = READ, priority: int = P2_NORMAL, **kwargs: Any) -> Any:
        operation = getattr(self.client, method)
        peer_key = self._peer_key(args[0] if args else None)
        request_hash, payload_size = request_fingerprint(method, args, kwargs)
        operation_id = uuid.uuid4().hex
        for attempt in range(self.retries + 1):
            started_at = time.monotonic()
            timestamp = time.time()
            try:
                result = await self.traffic.execute(method, lambda: operation(*args, **kwargs), peer_key=peer_key, operation_class=operation_class, priority=priority)
                await self._record(operation_id=operation_id, timestamp=timestamp, started_at=started_at, method=method, peer_key=peer_key, operation_class=operation_class, request_hash=request_hash, payload_size=payload_size, result_classification="SUCCESS", retry_count=attempt)
                return result
            except FloodWaitError as exc:
                wait = float(exc.seconds)
                await self._record(operation_id=operation_id, timestamp=timestamp, started_at=started_at, method=method, peer_key=peer_key, operation_class=operation_class, request_hash=request_hash, payload_size=payload_size, result_classification="FLOOD_WAIT", error_class=type(exc).__name__, retry_count=attempt, flood_wait_seconds=wait)
                if attempt >= self.retries or wait <= 0 or wait > self.flood_wait_cap:
                    raise ExternalServiceError("Telegram rate limit prevented the operation.") from exc
                self.traffic.record_flood_wait(method, wait, peer_key=peer_key)
            except SlowModeWaitError as exc:
                wait = float(exc.seconds)
                await self._record(operation_id=operation_id, timestamp=timestamp, started_at=started_at, method=method, peer_key=peer_key, operation_class=operation_class, request_hash=request_hash, payload_size=payload_size, result_classification="SLOW_MODE", error_class=type(exc).__name__, retry_count=attempt, slow_mode_seconds=wait)
                if attempt >= self.retries or wait <= 0 or wait > self.flood_wait_cap:
                    raise ExternalServiceError("Telegram slow mode prevented the operation.") from exc
                self.traffic.record_slow_mode(method, wait, peer_key=peer_key)
            except asyncio.TimeoutError as exc:
                await self._record(operation_id=operation_id, timestamp=timestamp, started_at=started_at, method=method, peer_key=peer_key, operation_class=operation_class, request_hash=request_hash, payload_size=payload_size, result_classification="TIMEOUT", error_class=type(exc).__name__, retry_count=attempt)
                raise TimeoutError("Telegram operation timed out.") from exc
            except Exception as exc:
                peer_flood = type(exc).__name__ == "PeerFloodError"
                await self._record(operation_id=operation_id, timestamp=timestamp, started_at=started_at, method=method, peer_key=peer_key, operation_class=operation_class, request_hash=request_hash, payload_size=payload_size, result_classification="PEER_FLOOD" if peer_flood else "ERROR", error_class=type(exc).__name__, retry_count=attempt, peer_flood=peer_flood)
                raise
        raise ExternalServiceError("Telegram operation failed.")

    @staticmethod
    def _peer_key(entity: Any) -> str | None:
        return None if entity is None else str(entity)
