"""Durable job contract for bounded Telegram archival."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelegramArchiveRequest:
    """Validated, bounded input for a future archive worker."""

    peer: str
    limit: int = 100
    min_message_id: int = 0
    include_media: bool = False

    MAX_PEER_CHARS = 256
    MAX_LIMIT = 500
    MAX_MESSAGE_ID = 2**63 - 1

    def __post_init__(self) -> None:
        if not self.peer or len(self.peer) > self.MAX_PEER_CHARS:
            raise ValueError("Archive peer is invalid")
        if not 1 <= int(self.limit) <= self.MAX_LIMIT:
            raise ValueError("Archive limit exceeds configured bound")
        if not 0 <= int(self.min_message_id) <= self.MAX_MESSAGE_ID:
            raise ValueError("Archive message cursor is invalid")
        if not isinstance(self.include_media, bool):
            raise ValueError("Archive include_media must be boolean")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "peer": self.peer,
            "limit": int(self.limit),
            "min_message_id": int(self.min_message_id),
            "include_media": self.include_media,
            "schema_version": 1,
        }

    @property
    def idempotency_key(self) -> str:
        canonical = json.dumps(self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"telegram-archive:v1:{digest}"


class TelegramArchiveJobModel:
    """Build the durable JobEngine contract without executing Telegram work."""

    JOB_TYPE = "TELEGRAM_ARCHIVE"
    RESOURCE_CLASS = "telegram_archive"
    PRIORITY = 4

    @classmethod
    def request(cls, peer: str, *, limit: int = 100, min_message_id: int = 0, include_media: bool = False) -> TelegramArchiveRequest:
        return TelegramArchiveRequest(peer=peer, limit=limit, min_message_id=min_message_id, include_media=include_media)

    @classmethod
    def enqueue_kwargs(cls, request: TelegramArchiveRequest) -> dict[str, Any]:
        if not isinstance(request, TelegramArchiveRequest):
            raise TypeError("request must be TelegramArchiveRequest")
        return {
            "job_type": cls.JOB_TYPE,
            "payload": request.payload,
            "idempotency_key": request.idempotency_key,
            "priority": cls.PRIORITY,
            "resource_class": cls.RESOURCE_CLASS,
        }
