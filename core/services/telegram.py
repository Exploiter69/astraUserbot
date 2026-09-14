"""Telegram operation facade with centralized traffic governance."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from telethon.errors import FloodWaitError

from core.errors import ExternalServiceError, TimeoutError
from core.services.telegram_traffic import (
    DESTRUCTIVE,
    DISCOVERY,
    MEDIA,
    P1_INTERACTIVE,
    P2_NORMAL,
    READ,
    TelegramTrafficController,
    WRITE,
)

logger = logging.getLogger("astra.services.telegram")


class TelegramFacade:
    """Centralize common Telegram operations while keeping raw Telethon available."""

    def __init__(
        self,
        client: Any,
        *,
        flood_wait_cap: float = 60.0,
        retries: int = 1,
        max_concurrency: int = 8,
        per_method_limit: int = 4,
        per_peer_limit: int = 2,
        max_queue: int = 512,
    ) -> None:
        self.client = client
        self.flood_wait_cap = max(0.0, float(flood_wait_cap))
        self.retries = max(0, int(retries))
        self.traffic = TelegramTrafficController(
            max_concurrency=max_concurrency,
            per_method_limit=per_method_limit,
            per_peer_limit=per_peer_limit,
            max_queue=max_queue,
        )

    async def start(self) -> None:
        await self.traffic.start()

    async def close(self) -> None:
        await self.traffic.close()

    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any:
        return await self._call(
            "send_message",
            entity,
            message,
            operation_class=WRITE,
            priority=P1_INTERACTIVE,
            **kwargs,
        )

    async def send_file(
        self,
        entity: Any,
        file: Any,
        *,
        caption: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if caption is not None:
            kwargs["caption"] = caption
        return await self._call(
            "send_file",
            entity,
            file,
            operation_class=MEDIA,
            priority=P2_NORMAL,
            **kwargs,
        )

    async def edit_message(self, entity: Any, message: Any, text: str, **kwargs: Any) -> Any:
        return await self._call(
            "edit_message",
            entity,
            message,
            text,
            operation_class=WRITE,
            priority=P1_INTERACTIVE,
            **kwargs,
        )

    async def delete_messages(
        self,
        entity: Any,
        message_ids: int | Sequence[int],
        **kwargs: Any,
    ) -> Any:
        return await self._call(
            "delete_messages",
            entity,
            message_ids,
            operation_class=DESTRUCTIVE,
            priority=P1_INTERACTIVE,
            **kwargs,
        )

    async def get_entity(self, entity: Any) -> Any:
        return await self._call(
            "get_entity",
            entity,
            operation_class=DISCOVERY,
            priority=P2_NORMAL,
        )

    def traffic_snapshot(self) -> dict[str, Any]:
        return self.traffic.snapshot()

    async def _call(
        self,
        method: str,
        *args: Any,
        operation_class: str = READ,
        priority: int = P2_NORMAL,
        **kwargs: Any,
    ) -> Any:
        operation = getattr(self.client, method)
        peer_key = self._peer_key(args[0] if args else None)
        for attempt in range(self.retries + 1):
            try:
                return await self.traffic.execute(
                    method,
                    lambda: operation(*args, **kwargs),
                    peer_key=peer_key,
                    operation_class=operation_class,
                    priority=priority,
                )
            except FloodWaitError as exc:
                wait = float(exc.seconds)
                if attempt >= self.retries or wait <= 0 or wait > self.flood_wait_cap:
                    raise ExternalServiceError("Telegram rate limit prevented the operation.") from exc
                self.traffic.record_flood_wait(method, wait, peer_key=peer_key)
                logger.warning(
                    "Telegram flood wait operation=%s seconds=%s retry=%s",
                    method,
                    int(wait),
                    attempt + 1,
                )
            except asyncio.TimeoutError as exc:
                raise TimeoutError("Telegram operation timed out.") from exc
        raise ExternalServiceError("Telegram operation failed.")

    @staticmethod
    def _peer_key(entity: Any) -> str | None:
        if entity is None:
            return None
        return str(entity)
