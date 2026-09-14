"""Durable bounded Telegram archive execution on top of JobEngine."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

from core.errors import ResourceError
from core.services.jobs import Job, JobEngine, JobError
from core.services.media import MediaService
from core.services.search import SearchService
from core.services.storage import StorageService
from core.services.telegram import TelegramFacade
from core.services.telegram_archive import TelegramArchiveJobModel, TelegramArchiveRequest


class TelegramArchiveService:
    """Execute bounded, restart-safe Telegram archive jobs."""

    BATCH_SIZE = 100
    MAX_MEDIA_PER_JOB = 50
    MAX_MEDIA_BYTES_PER_JOB = 512 * 1024 * 1024
    MAX_TEXT_CHARS = 64 * 1024
    MAX_METADATA_CHARS = 32 * 1024
    SOURCE = "archive_message"
    CURSOR_EVENT = "ARCHIVE_CURSOR"

    def __init__(self, storage: StorageService, telegram: TelegramFacade, search: SearchService, media: MediaService, jobs: JobEngine, project_root: str | Path) -> None:
        self.storage = storage
        self.telegram = telegram
        self.search = search
        self.media = media
        self.jobs = jobs
        self.project_root = Path(project_root).resolve()
        self.media_root = self.project_root / "data" / "archive" / "media"
        self._started = False
        if TelegramArchiveJobModel.JOB_TYPE not in self.jobs.handlers:
            self.jobs.register_handler(TelegramArchiveJobModel.JOB_TYPE, self._handle_job)

    async def start(self) -> None:
        if self._started:
            return
        await self.storage.fetchone("SELECT 1 FROM search_documents LIMIT 1")
        self.media_root.mkdir(parents=True, exist_ok=True)
        self._started = True

    async def close(self) -> None:
        self._started = False

    async def enqueue(self, peer: str, *, limit: int = 100, min_message_id: int = 0, include_media: bool = False, owner: str | None = None) -> Job:
        request = TelegramArchiveJobModel.request(peer, limit=limit, min_message_id=min_message_id, include_media=include_media)
        return await self.jobs.enqueue(owner=owner, **TelegramArchiveJobModel.enqueue_kwargs(request))

    async def search_archive(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        cleaned = self.search._clean_query(query)
        if not cleaned:
            return []
        limit = max(1, min(int(limit), 50))
        rows = await self.storage.fetchall(
            "SELECT d.ref,d.title,snippet(search_fts,2,'','', '…', 18),bm25(search_fts) FROM search_fts JOIN search_documents d ON d.id=search_fts.id WHERE d.source=? AND search_fts MATCH ? ORDER BY bm25(search_fts) LIMIT ?",
            (self.SOURCE, cleaned, limit),
        )
        return [{"ref": str(row[0]), "title": str(row[1]), "snippet": str(row[2]), "rank": float(row[3])} for row in rows]

    async def list_archive(self, peer: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        if peer:
            rows = await self.storage.fetchall("SELECT ref,title,content,updated_at FROM search_documents WHERE source=? AND ref LIKE ? ORDER BY updated_at DESC LIMIT ?", (self.SOURCE, f"{peer}:%", limit))
        else:
            rows = await self.storage.fetchall("SELECT ref,title,content,updated_at FROM search_documents WHERE source=? ORDER BY updated_at DESC LIMIT ?", (self.SOURCE, limit))
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                metadata = json.loads(str(row[2]))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {"text": str(row[2])}
            metadata.update({"ref": str(row[0]), "title": str(row[1]), "updated_at": float(row[3])})
            result.append(metadata)
        return result

    async def _handle_job(self, job: Job) -> dict[str, Any]:
        try:
            request = TelegramArchiveRequest(
                peer=str(job.payload.get("peer", "")),
                limit=int(job.payload.get("limit", 100)),
                min_message_id=int(job.payload.get("min_message_id", 0)),
                include_media=bool(job.payload.get("include_media", False)),
            )
        except (TypeError, ValueError) as exc:
            raise JobError("Archive job payload is invalid", code="ARCHIVE_INVALID_PAYLOAD") from exc

        state = await self._load_cursor(job.id) or {"cursor": 0, "archived": 0, "media_archived": 0, "media_bytes": 0}
        cursor = int(state.get("cursor", 0))
        archived = int(state.get("archived", 0))
        media_archived = int(state.get("media_archived", 0))
        media_bytes = int(state.get("media_bytes", 0))
        remaining = max(0, request.limit - archived)
        batches = 0

        while remaining > 0:
            batch_limit = min(self.BATCH_SIZE, remaining)
            try:
                messages = await self.telegram.get_messages(request.peer, limit=batch_limit, max_id=cursor or None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise JobError("Telegram archive fetch failed", code="ARCHIVE_FETCH_FAILED", retryable=True) from exc
            if not messages:
                break

            ids: list[int] = []
            for message in messages:
                message_id = getattr(message, "id", None)
                if not isinstance(message_id, int) or message_id <= 0:
                    continue
                if request.min_message_id and message_id < request.min_message_id:
                    continue
                ids.append(message_id)
                metadata = await self._archive_message(request, message, job_id=job.id, media_bytes_used=media_bytes, media_count=media_archived)
                media_bytes += int(metadata.get("media_size", 0) or 0)
                media_archived += 1 if metadata.get("media_path") else 0
                archived += 1
                remaining -= 1
                if remaining <= 0:
                    break

            if not ids:
                break
            next_cursor = max(request.min_message_id, min(ids) - 1)
            if cursor and next_cursor >= cursor:
                break
            cursor = next_cursor
            batches += 1
            await self._save_cursor(job.id, cursor, archived, media_archived, media_bytes)
            await self.jobs.update_progress(job.id, min(1.0, archived / request.limit))
            if len(messages) < batch_limit or cursor <= request.min_message_id:
                break

        await self._save_cursor(job.id, cursor, archived, media_archived, media_bytes, completed=True)
        return {"peer": request.peer, "requested": request.limit, "archived": archived, "media_archived": media_archived, "media_bytes": media_bytes, "batches": batches, "cursor": cursor}

    async def _archive_message(self, request: TelegramArchiveRequest, message: Any, *, job_id: str, media_bytes_used: int, media_count: int) -> dict[str, Any]:
        message_id = int(message.id)
        peer = request.peer
        now = time.time()
        text = str(getattr(message, "message", None) or getattr(message, "text", None) or "")[: self.MAX_TEXT_CHARS]
        date = getattr(message, "date", None)
        edit_date = getattr(message, "edit_date", None)
        media = getattr(message, "media", None)
        metadata: dict[str, Any] = {
            "schema_version": 1, "job_id": job_id, "peer": peer, "message_id": message_id,
            "sender_id": getattr(message, "sender_id", None), "reply_to_message_id": getattr(message, "reply_to_msg_id", None),
            "observed_at": date.timestamp() if hasattr(date, "timestamp") else now,
            "edited_at": edit_date.timestamp() if hasattr(edit_date, "timestamp") else None,
            "text": text, "media": bool(media), "media_path": None, "media_sha256": None,
            "media_size": 0, "media_type": None, "media_name": None,
            "media_status": "NONE" if media is None else "PENDING",
        }

        if media is not None and request.include_media:
            if media_count >= self.MAX_MEDIA_PER_JOB:
                metadata["media_status"] = "SKIPPED_JOB_MEDIA_COUNT_LIMIT"
            else:
                try:
                    self.media.validate_telegram_media(media)
                    declared = getattr(getattr(media, "file", None), "size", None)
                    if isinstance(declared, (int, float)) and media_bytes_used + int(declared) > self.MAX_MEDIA_BYTES_PER_JOB:
                        raise ResourceError("Archive media byte budget reached")
                    media_meta = await self._archive_media(media)
                    if media_meta:
                        metadata.update(media_meta)
                        if media_bytes_used + int(metadata["media_size"]) > self.MAX_MEDIA_BYTES_PER_JOB:
                            (self.project_root / str(metadata["media_path"])).unlink(missing_ok=True)
                            metadata.update({"media_path": None, "media_sha256": None, "media_size": 0, "media_status": "SKIPPED_JOB_MEDIA_BYTES_LIMIT"})
                except asyncio.CancelledError:
                    raise
                except (ResourceError, OSError, ValueError) as exc:
                    metadata.update({"media_status": "SKIPPED_LIMIT_OR_STORAGE", "media_error": type(exc).__name__})
                except Exception as exc:
                    metadata.update({"media_status": "FAILED", "media_error": type(exc).__name__})
        elif media is not None:
            metadata["media_status"] = "METADATA_ONLY"

        encoded = self._encode_metadata(metadata)
        await self.search.upsert(source=self.SOURCE, ref=f"{peer}:{message_id}", title=f"{peer} #{message_id}", content=encoded)
        return metadata

    def _encode_metadata(self, metadata: dict[str, Any]) -> str:
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        while len(encoded) > self.MAX_METADATA_CHARS and metadata.get("text"):
            text = str(metadata["text"])
            metadata["text"] = text[: max(0, len(text) - 4096)]
            encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) > self.MAX_METADATA_CHARS:
            for key in ("media_error", "media_name", "reply_to_message_id", "edited_at"):
                metadata.pop(key, None)
                encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if len(encoded) <= self.MAX_METADATA_CHARS:
                    break
        if len(encoded) > self.MAX_METADATA_CHARS:
            raise ResourceError("Archive metadata exceeds configured storage limit")
        return encoded

    async def _archive_media(self, media: Any) -> dict[str, Any] | None:
        workspace = await self.media.create_workspace("archive")
        try:
            downloaded = await self.media.download_telegram_media(self.telegram.download_media, media, workspace=workspace)
            if not downloaded:
                return None
            path = Path(str(downloaded))
            if not path.is_file():
                return None
            size = path.stat().st_size
            if size <= 0 or size > self.media.max_input_bytes:
                raise ResourceError("Downloaded archive media exceeds configured size limits")
            digest = await asyncio.to_thread(self._sha256_file, path)
            suffix = path.suffix.lower()
            destination = self.media_root / digest[:2] / (digest + suffix)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                path.unlink(missing_ok=True)
            else:
                os.replace(path, destination)
            file_obj = getattr(media, "file", None)
            name = getattr(file_obj, "name", None) or path.name
            return {
                "media_path": str(destination.relative_to(self.project_root)), "media_sha256": digest,
                "media_size": size, "media_type": getattr(file_obj, "mime_type", None) or mimetypes.guess_type(str(name))[0],
                "media_name": str(name)[:500], "media_status": "ARCHIVED",
            }
        finally:
            await self.media.cleanup(workspace)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def _load_cursor(self, job_id: str) -> dict[str, Any] | None:
        row = await self.storage.fetchone("SELECT payload_json FROM job_events WHERE job_id=? AND event_type=? ORDER BY id DESC LIMIT 1", (job_id, self.CURSOR_EVENT))
        if not row:
            return None
        try:
            return dict(json.loads(str(row[0])))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    async def _save_cursor(self, job_id: str, cursor: int, archived: int, media_archived: int, media_bytes: int, *, completed: bool = False) -> None:
        payload = json.dumps({"cursor": int(cursor), "archived": int(archived), "media_archived": int(media_archived), "media_bytes": int(media_bytes), "completed": completed}, sort_keys=True, separators=(",", ":"))
        await self.storage.execute("INSERT INTO job_events(job_id,event_type,payload_json,created_at) VALUES(?,?,?,?)", (job_id, self.CURSOR_EVENT, payload, time.time()))
