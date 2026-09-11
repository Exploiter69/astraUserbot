"""Shared bounded HTTP client with pooling, host limits and transient retries."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp

from core.errors import ExternalServiceError, ResourceError, TimeoutError

logger = logging.getLogger("astra.services.http")


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        return self.body.decode(errors="replace")


class HttpService:
    """Own one aiohttp session and apply shared network/resource policy."""

    RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        total_timeout: float = 30.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 25.0,
        connection_limit: int = 20,
        per_host_limit: int = 5,
        response_limit: int = 4 * 1024 * 1024,
        retries: int = 2,
        retry_delay: float = 0.5,
    ) -> None:
        if response_limit <= 0 or connection_limit <= 0 or per_host_limit <= 0:
            raise ValueError("HTTP limits must be positive")
        self.response_limit = int(response_limit)
        self.retries = max(0, int(retries))
        self.retry_delay = max(0.0, float(retry_delay))
        self._timeout = aiohttp.ClientTimeout(
            total=total_timeout,
            connect=connect_timeout,
            sock_connect=connect_timeout,
            sock_read=read_timeout,
        )
        self._connection_limit = int(connection_limit)
        self._per_host_limit = int(per_host_limit)
        self._connector: aiohttp.TCPConnector | None = None
        self._session: aiohttp.ClientSession | None = None
        self._host_limits: defaultdict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self._per_host_limit)
        )
        self._lock = asyncio.Lock()

    @property
    def session(self) -> aiohttp.ClientSession | None:
        return self._session

    async def start(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is not None and not self._session.closed:
                return self._session
            self._connector = aiohttp.TCPConnector(
                limit=self._connection_limit,
                limit_per_host=self._per_host_limit,
                ttl_dns_cache=300,
                keepalive_timeout=30,
            )
            self._session = aiohttp.ClientSession(timeout=self._timeout, connector=self._connector)
            return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._session = None
            self._connector = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        data: object | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
        response_limit: int | None = None,
        retries: int | None = None,
    ) -> HttpResponse:
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP URL must use http:// or https://")
        limit = self.response_limit if response_limit is None else int(response_limit)
        if limit <= 0:
            raise ValueError("response_limit must be positive")
        attempts = self.retries if retries is None else max(0, int(retries))
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            raise ValueError("HTTP URL has no host")
        session = await self.start()
        host_limit = self._host_limits[host]
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout is not None else None

        for attempt in range(attempts + 1):
            try:
                async with host_limit:
                    async with session.request(
                        method.upper(),
                        url,
                        headers=headers,
                        params=params,
                        data=data,
                        allow_redirects=allow_redirects,
                        timeout=request_timeout,
                    ) as response:
                        body = await self._read_bounded(response, limit)
                        result = HttpResponse(response.status, dict(response.headers), body, str(response.url))
                        if response.status in self.RETRY_STATUSES and attempt < attempts:
                            await asyncio.sleep(self._retry_delay(attempt))
                            continue
                        return result
            except asyncio.TimeoutError as exc:
                if attempt < attempts:
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                raise TimeoutError("HTTP request timed out") from exc
            except aiohttp.ClientError as exc:
                if attempt < attempts:
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                raise ExternalServiceError("HTTP request failed") from exc
            except asyncio.CancelledError:
                raise

        raise ExternalServiceError("HTTP request failed")

    async def get(self, url: str, **kwargs) -> HttpResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> HttpResponse:
        return await self.request("POST", url, **kwargs)

    async def head(self, url: str, **kwargs) -> HttpResponse:
        return await self.request("HEAD", url, **kwargs)

    async def _read_bounded(self, response: aiohttp.ClientResponse, limit: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.content.iter_chunked(65_536):
            total += len(chunk)
            if total > limit:
                raise ResourceError("HTTP response exceeded the configured size limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _retry_delay(self, attempt: int) -> float:
        return self.retry_delay * (2**attempt)
