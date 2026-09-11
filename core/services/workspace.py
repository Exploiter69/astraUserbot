"""Canonical filesystem roots and per-workspace artifact lifecycle."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from core.errors import ResourceError

logger = logging.getLogger("astra.services.workspace")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(slots=True)
class Workspace:
    """A unique directory intended to isolate one operation or job."""

    path: Path
    created_at: float

    def resolve(self, relative: str | Path = ".") -> Path:
        candidate = (self.path / relative).resolve()
        try:
            candidate.relative_to(self.path.resolve())
        except ValueError as exc:
            raise ValueError("Workspace path escapes workspace root") from exc
        return candidate


class WorkspaceService:
    """Own temporary workspaces and bounded filesystem policy."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        workspace_dir: str | Path | None = None,
        max_file_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = (self.project_root / "data" / "workspaces").resolve() if workspace_dir is None else Path(workspace_dir).resolve()
        self.max_file_bytes = int(max_file_bytes)
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def create(self, name: str | None = None) -> Workspace:
        await self.start()
        prefix = "job"
        if name is not None:
            if not _SAFE_NAME.fullmatch(name):
                raise ValueError("Invalid workspace name")
            prefix = name
        async with self._lock:
            for _ in range(100):
                suffix = f"{time.time_ns():x}"
                path = self.root / f"{prefix}-{suffix}"
                try:
                    path.mkdir(parents=False)
                except FileExistsError:
                    continue
                return Workspace(path=path, created_at=time.time())
        raise ResourceError("Unable to allocate a unique workspace.")

    def safe_path(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escapes workspace root") from exc
        return candidate

    def validate_file(self, path: str | Path) -> Path:
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("File is outside the managed workspace root") from exc
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate.stat().st_size > self.max_file_bytes:
            raise ResourceError("File exceeds the configured size limit.")
        return candidate

    async def cleanup(self, workspace: Workspace | str | Path) -> None:
        path = workspace.path if isinstance(workspace, Workspace) else Path(workspace)
        path = path.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Cannot clean outside workspace root") from exc
        if path == self.root:
            raise ValueError("Cannot remove workspace root")
        if path.exists():
            await asyncio.to_thread(shutil.rmtree, path)

    async def cleanup_orphans(self, *, older_than_seconds: float = 86_400) -> int:
        await self.start()
        cutoff = time.time() - max(0.0, older_than_seconds)
        removed = 0
        for path in self.root.iterdir():
            if not path.is_dir() or path.stat().st_mtime > cutoff:
                continue
            try:
                await self.cleanup(path)
                removed += 1
            except (OSError, ValueError):
                logger.warning("Failed to clean workspace path=%s", path, exc_info=True)
        return removed
