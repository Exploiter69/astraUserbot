"""Small Telegram operation facade around the raw Telethon client."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from telethon.errors import FloodWaitError

from core.errors import ExternalServiceError, TimeoutError

logger = logging.getLogger("astra.services.telegram")


class TelegramFacade:
    """Centralize common Telegram operations while keeping raw Telethon available."""

    def __init__(self, client: Any, *, flood_wait_cap: float = 60.0, retries: int = 1) -> None:
        self.client = client
        self.flood_wait_cap = max(0.0, float(flood_wait_cap))
        self.retries = max(0, int(retries))

    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any:
        return await self._call("send_message", entity, message, **kwargs)

    async def send_file(self, entity: Any, file: Any, *, caption: str | None = None, **kwargs: Any) -> Any:
        if caption is not None:
            kwargs["caption"] = caption
        return await self._call("send_file", entity, file, **kwargs)

    async def edit_message(self, entity: Any, message: Any, text: str, **kwargs: Any) -> Any:
        return await self._call("edit_message", entity, message, text, **kwargs)

    async def delete_messages(self, entity: Any, message_ids: int | Sequence[int], **kwargs: Any) -> Any:
        return await self._call("delete_messages", entity, message_ids, **kwargs)

    async def get_entity(self, entity: Any) -> Any:
        return await self._call("get_entity", entity)

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        operation = getattr(self.client, method)
        for attempt in range(self.retries + 1):
            try:
                return await operation(*args, **kwargs)
            except FloodWaitError as exc:
                wait = float(exc.seconds)
                if attempt >= self.retries or wait <= 0 or wait > self.flood_wait_cap:
                    raise ExternalServiceError("Telegram rate limit prevented the operation.") from exc
                logger.warning("Telegram flood wait operation=%s seconds=%s", method, int(wait))
                await asyncio.sleep(wait)
            except asyncio.TimeoutError as exc:
                raise TimeoutError("Telegram operation timed out.") from exc
            except asyncio.CancelledError:
                raise
        raise ExternalServiceError("Telegram operation failed.")
