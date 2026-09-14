"""Durable, bounded Telegram operation flight recorder."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from typing import Any, Protocol

logger = logging.getLogger("astra.services.telegram_recorder")


class StorageProtocol(Protocol):
    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...


class TelegramOperationRecorder:
    """Persist bounded Telegram operation telemetry without request contents."""

    def __init__(self, storage: StorageProtocol, *, max_rows: int = 10_000) -> None:
        self.storage = storage
        self.max_rows = max(1, int(max_rows))

    async def record(
        self,
        *,
        operation_id: str,
        started_at: float,
        method: str,
        peer_id: str | None,
        operation_class: str,
        request_hash: str,
        result_classification: str,
        latency_ms: float,
        flood_wait_seconds: float | None = None,
        slow_mode_seconds: float | None = None,
        peer_flood: bool = False,
        error_class: str | None = None,
        retry_count: int = 0,
        payload_size: int | None = None,
        job_id: str | None = None,
        source: str | None = None,
    ) -> None:
        try:
            await self.storage.execute(
                """
                INSERT INTO telegram_operations(
                    operation_id, timestamp, method, peer_id, operation_class,
                    request_hash, result_classification, latency_ms,
                    flood_wait_seconds, slow_mode_seconds, peer_flood,
                    error_class, retry_count, payload_size, job_id, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, float(started_at), str(method), peer_id,
                    str(operation_class), request_hash, str(result_classification),
                    max(0.0, float(latency_ms)),
                    None if flood_wait_seconds is None else max(0.0, float(flood_wait_seconds)),
                    None if slow_mode_seconds is None else max(0.0, float(slow_mode_seconds)),
                    1 if peer_flood else 0, error_class, max(0, int(retry_count)),
                    None if payload_size is None else max(0, int(payload_size)),
                    job_id, source,
                ),
            )
            await self.storage.execute(
                """
                DELETE FROM telegram_operations
                WHERE id NOT IN (
                    SELECT id FROM telegram_operations
                    ORDER BY timestamp DESC, id DESC
                    LIMIT ?
                )
                """,
                (self.max_rows,),
            )
        except Exception:
            # Telemetry must never become an authority or break Telegram traffic.
            logger.warning("Telegram flight recorder write failed", exc_info=True)


def request_fingerprint(
    method: str, args: Sequence[Any], kwargs: dict[str, Any]
) -> tuple[str, int]:
    """Hash request material and return its approximate byte size without persisting it."""
    digest = hashlib.sha256()
    payload_size = 0

    def feed(value: Any) -> None:
        nonlocal payload_size
        if isinstance(value, bytes):
            raw = value
        elif isinstance(value, bytearray):
            raw = bytes(value)
        elif isinstance(value, str):
            raw = value.encode("utf-8", "replace")
        else:
            raw = repr(value).encode("utf-8", "replace")
        payload_size += len(raw)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)

    feed(method)
    for value in args:
        feed(value)
    for key in sorted(kwargs):
        feed(key)
        feed(kwargs[key])
    return digest.hexdigest(), payload_size
