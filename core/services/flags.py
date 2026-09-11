from __future__ import annotations

import json
from typing import Any

from core.services.storage import StorageService


class FeatureFlagService:
    """Persistent, explicit feature flags with safe defaults and bounded values."""

    MAX_FLAGS = 256

    def __init__(self, storage: StorageService) -> None:
        self.storage = storage
        self._started = False

    async def start(self) -> None:
        row = await self.storage.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='feature_flags'")
        if not row:
            raise RuntimeError("Feature flag schema migration is not applied")
        self._started = True

    async def close(self) -> None:
        self._started = False

    async def enabled(self, name: str, default: bool = False) -> bool:
        row = await self.storage.fetchone("SELECT enabled FROM feature_flags WHERE name=?", (str(name)[:120],))
        return bool(row[0]) if row else bool(default)

    async def set(self, name: str, enabled: bool, metadata: dict[str, Any] | None = None) -> None:
        if not name or len(name) > 120:
            raise ValueError("Invalid feature flag name")
        row = await self.storage.fetchone("SELECT COUNT(*) FROM feature_flags")
        existing = await self.storage.fetchone("SELECT 1 FROM feature_flags WHERE name=?", (name,))
        if existing is None and row is not None and int(row[0]) >= self.MAX_FLAGS:
            raise ValueError("Feature flag capacity reached")
        payload = json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True)[:4000]
        await self.storage.execute(
            "INSERT INTO feature_flags(name,enabled,metadata_json,updated_at) VALUES(?,?,?,strftime('%s','now')) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
            (name, int(enabled), payload),
        )

    async def list(self) -> list[dict[str, Any]]:
        rows = await self.storage.fetchall("SELECT name,enabled,metadata_json,updated_at FROM feature_flags ORDER BY name")
        result = []
        for row in rows:
            try:
                metadata = json.loads(row[2])
            except (TypeError, ValueError):
                metadata = {}
            result.append({"name": row[0], "enabled": bool(row[1]), "metadata": metadata, "updated_at": row[3]})
        return result
