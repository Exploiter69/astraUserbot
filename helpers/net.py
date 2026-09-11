"""Compatibility access to the shared HttpService session."""

from __future__ import annotations

import aiohttp


async def get_http_service():
    """Return the process ApplicationContext HTTP service when available."""
    try:
        from core.context import get_application_context

        context = get_application_context()
        if context is not None:
            return context.get("http")
    except (ImportError, LookupError):
        pass
    return None


def get_session() -> aiohttp.ClientSession:
    """Legacy synchronous accessor backed by the shared service when started."""
    try:
        from core.context import get_application_context

        context = get_application_context()
        if context is not None:
            service = context.get("http")
            session = service.session
            if session is not None and not session.closed:
                return session
    except (ImportError, LookupError):
        pass
    raise RuntimeError("Shared HttpService is not started")


async def close_session() -> None:
    """Compatibility no-op; ApplicationContext owns HTTP session shutdown."""
    return None
