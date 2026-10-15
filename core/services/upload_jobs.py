"""Durable UPLOAD jobs with conservative published-media reconciliation.

UPLOAD means a media message accepted into a destination's visible history.
Temporary upload handles/chunks are not publication evidence.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from core.services.jobs import Job, JobEngine, JobError, ReconcileContext, ReconcileOutcome
from core.services.storage import StorageService

UPLOAD_JOB_TYPE = "UPLOAD"
UPLOAD_EFFECT_CLASS = "UPLOAD"
HISTORY_SCAN_LIMIT = 100
CLOCK_SKEW_SECONDS = 5.0


class AuthoritativeUploadRejection(Exception):
    """Explicit platform/test signal that publication was not accepted."""


def _normalized_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "").replace("\r\n", "\n").replace("\r", "\n"))


def _message_id(message: Any) -> int | None:
    value = getattr(message, "id", getattr(message, "message_id", None))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _timestamp(message: Any) -> float | None:
    value = getattr(message, "date", None)
    if isinstance(value, (int, float)):
        return float(value)
    method = getattr(value, "timestamp", None)
    if callable(method):
        try:
            return float(method())
        except (TypeError, ValueError, OSError):
            return None
    return None


def _message_caption(message: Any) -> str:
    value = getattr(message, "message", None)
    if value is None:
        value = getattr(message, "text", None)
    if value is None:
        value = getattr(message, "caption", None)
    return _normalized_text(value)


def _media_metadata(message: Any) -> dict[str, Any] | None:
    """Extract only stable, observable metadata; never treat an upload handle as media."""
    media = getattr(message, "media", None)
    if media is None:
        media = getattr(message, "photo", None) or getattr(message, "document", None)
    file_obj = getattr(message, "file", None)
    document = getattr(media, "document", None) or getattr(message, "document", None)
    photo = getattr(media, "photo", None) or getattr(message, "photo", None)
    if media is None and file_obj is None and document is None and photo is None:
        return None

    name = getattr(file_obj, "name", None)
    size = getattr(file_obj, "size", None)
    mime = getattr(file_obj, "mime_type", None)
    if document is not None:
        size = size if size is not None else getattr(document, "size", None)
        mime = mime or getattr(document, "mime_type", None)
        for attribute in getattr(document, "attributes", ()) or ():
            attr_name = type(attribute).__name__.lower()
            if "filename" in attr_name:
                name = name or getattr(attribute, "file_name", None)
    media_id = getattr(document, "id", None) if document is not None else getattr(photo, "id", None)
    kind = "document" if document is not None else ("photo" if photo is not None else type(media).__name__)
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    return {
        "kind": kind,
        "file_name": os.path.basename(str(name)) if name else None,
        "size": size,
        "mime_type": str(mime).lower() if mime else None,
        "media_id": str(media_id) if media_id is not None else None,
    }


def _expected_media(payload: dict[str, Any]) -> dict[str, Any]:
    explicit = payload.get("media_metadata")
    expected: dict[str, Any] = {}
    if isinstance(explicit, dict):
        for key in ("kind", "file_name", "size", "mime_type", "media_id"):
            if explicit.get(key) is not None:
                expected[key] = explicit[key]
    source = payload.get("file", payload.get("path", payload.get("media_path")))
    if source is not None:
        path = Path(str(source))
        expected.setdefault("file_name", path.name)
        try:
            if path.is_file():
                expected.setdefault("size", path.stat().st_size)
        except OSError:
            pass
    if expected.get("file_name"):
        expected["file_name"] = os.path.basename(str(expected["file_name"]))
    if expected.get("mime_type"):
        expected["mime_type"] = str(expected["mime_type"]).lower()
    if expected.get("size") is not None:
        try:
            expected["size"] = int(expected["size"])
        except (TypeError, ValueError):
            expected.pop("size", None)
    return expected


def _has_sufficient_media_identity(expected: dict[str, Any]) -> bool:
    strong = [key for key in ("file_name", "size", "mime_type", "media_id")
              if expected.get(key) is not None]
    # A Telegram media ID is itself a strong identifier. Otherwise require at
    # least two independent metadata fields; a filename alone is too ambiguous.
    return len(strong) >= 2 or (len(strong) == 1 and strong[0] == "media_id")


def _media_matches(observed: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if not observed or not _has_sufficient_media_identity(expected):
        return False
    identity_keys = ("file_name", "size", "mime_type", "media_id", "kind")
    compared = [key for key in identity_keys if expected.get(key) is not None]
    return bool(compared) and all(observed.get(key) == expected[key] for key in compared)


def _fingerprint(target: Any, caption: str, expected_media: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"target": str(target).strip(), "caption": _normalized_text(caption),
         "media": expected_media},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authoritative_rejection(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, AuthoritativeUploadRejection):
            return True
        if (getattr(current, "authoritative_not_applied", False) is True
                and getattr(current, "retry_safe", False) is True):
            return True
        current = current.__cause__ or current.__context__
    return False


class UploadJobAdapter:
    """Register one UPLOAD handler; reconcile visible published media, not chunks."""

    def __init__(self, jobs: JobEngine, telegram: Any, storage: StorageService) -> None:
        self.jobs = jobs
        self.telegram = telegram
        self.storage = storage
        if UPLOAD_JOB_TYPE not in jobs.handlers:
            jobs.register_handler(
                UPLOAD_JOB_TYPE, self.handle,
                effect_class=UPLOAD_EFFECT_CLASS, reconciler=self.reconcile,
            )

    async def _effect(self, job_id: str):
        rows = await self.storage.fetchall(
            "SELECT * FROM job_effects WHERE job_id=? AND effect_class=? AND required=1",
            (job_id, UPLOAD_EFFECT_CLASS),
        )
        if len(rows) != 1:
            raise JobError(
                "UPLOAD adapter requires exactly one required UPLOAD effect per job",
                code="UPLOAD_EFFECT_CARDINALITY",
            )
        return rows[0]

    async def _record_attempt(
        self, job: Job, target: Any, caption: str, expected: dict[str, Any],
        started_at: float, temporary_handle: Any = None,
    ) -> None:
        await self._effect(job.id)
        external = {"expected_media": expected, "caption": _normalized_text(caption)}
        # Retain a chunk/upload handle for diagnostics only. It is never a
        # published-message ID and cannot satisfy reconciliation.
        if temporary_handle is not None:
            external["temporary_upload_handle"] = str(temporary_handle)
        await self.storage.execute(
            """UPDATE job_effects
               SET target_json=?, external_ref_json=?, payload_fingerprint=?,
                   attempt_started_at=?, authoritative_rejection=0,
                   state='PENDING', reason=NULL, updated_at=?
               WHERE job_id=? AND effect_class=? AND required=1""",
            (json.dumps(target, separators=(",", ":"), ensure_ascii=False),
             json.dumps(external, separators=(",", ":"), ensure_ascii=False),
             _fingerprint(target, caption, expected), started_at, time.time(),
             job.id, UPLOAD_EFFECT_CLASS),
        )

    async def _record_published_id(self, job_id: str, message_id: int | None) -> None:
        row = await self.storage.fetchone(
            "SELECT external_ref_json FROM job_effects WHERE job_id=? AND effect_class=? AND required=1",
            (job_id, UPLOAD_EFFECT_CLASS),
        )
        try:
            external = json.loads(row["external_ref_json"]) if row and row["external_ref_json"] else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            external = {}
        if not isinstance(external, dict):
            external = {}
        if message_id is not None:
            external["published_message_id"] = int(message_id)
        await self.storage.execute(
            """UPDATE job_effects SET external_ref_json=?, state='HAPPENED',
               reason=NULL, updated_at=? WHERE job_id=? AND effect_class=? AND required=1""",
            (json.dumps(external, separators=(",", ":"), ensure_ascii=False),
             time.time(), job_id, UPLOAD_EFFECT_CLASS),
        )

    async def _record_rejection(self, job_id: str, error: BaseException) -> None:
        await self.storage.execute(
            """UPDATE job_effects SET authoritative_rejection=1, state='NOT_HAPPENED',
               reason=?, updated_at=? WHERE job_id=? AND effect_class=? AND required=1""",
            (f"AUTHORITATIVE_REJECTION:{type(error).__name__}"[:200], time.time(),
             job_id, UPLOAD_EFFECT_CLASS),
        )

    async def handle(self, job: Job) -> dict[str, Any]:
        target = job.payload.get("target", job.payload.get("peer_id"))
        source = job.payload.get("file", job.payload.get("path", job.payload.get("media_path")))
        caption = job.payload.get("caption", "")
        if target is None or source is None or not isinstance(caption, str):
            raise JobError(
                "UPLOAD payload requires target, file/path, and optional string caption",
                code="UPLOAD_INVALID_PAYLOAD",
            )
        expected = _expected_media(job.payload)
        if not _has_sufficient_media_identity(expected):
            raise JobError(
                "UPLOAD requires sufficient media identity metadata (e.g. filename plus size, or media ID)",
                code="UPLOAD_MEDIA_IDENTITY_REQUIRED",
            )
        started_at = time.time()
        await self._record_attempt(
            job, target, caption, expected, started_at,
            job.payload.get("temporary_upload_handle"),
        )
        try:
            result = await self.telegram.send_file(target, source, caption=caption or None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not _authoritative_rejection(exc):
                raise JobError(
                    "UPLOAD publication outcome is not authoritative",
                    code="UPLOAD_OUTCOME_UNKNOWN", retryable=True,
                ) from exc
            await self._record_rejection(job.id, exc)
            raise JobError(
                "Telegram authoritatively rejected the UPLOAD publication",
                code="UPLOAD_REJECTED", retryable=True,
            ) from exc

        # This adapter models one published media message. Batch results are
        # intentionally not guessed at; the reconciler will need history evidence.
        message = result[0] if isinstance(result, (list, tuple)) and len(result) == 1 else result
        message_id = _message_id(message) if not isinstance(result, (list, tuple)) or len(result) == 1 else None
        await self._record_published_id(job.id, message_id)
        return {"target": str(target), "published_message_id": message_id}

    async def reconcile(self, context: ReconcileContext) -> ReconcileOutcome:
        if context.effect_class != UPLOAD_EFFECT_CLASS:
            return ReconcileOutcome.UNKNOWN
        row = await self.storage.fetchone(
            """SELECT target_json, external_ref_json, payload_fingerprint,
                      attempt_started_at, authoritative_rejection
               FROM job_effects WHERE effect_id=?""",
            (context.effect_id,),
        )
        if row is None or not row["target_json"] or not row["external_ref_json"]:
            return ReconcileOutcome.UNKNOWN
        try:
            target = json.loads(row["target_json"])
            evidence = json.loads(row["external_ref_json"])
            expected = evidence["expected_media"]
            caption = evidence["caption"]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return ReconcileOutcome.UNKNOWN
        if (not isinstance(evidence, dict) or not isinstance(expected, dict)
                or not isinstance(caption, str) or not row["payload_fingerprint"]):
            return ReconcileOutcome.UNKNOWN
        started_at = row["attempt_started_at"] or context.attempt_started_at
        if started_at is None or target is None:
            return ReconcileOutcome.UNKNOWN
        try:
            started_at = float(started_at)
        except (TypeError, ValueError):
            return ReconcileOutcome.UNKNOWN

        client = getattr(self.telegram, "client", None)
        getter = getattr(client, "get_me", None) or getattr(self.telegram, "get_me", None)
        if getter is None:
            return ReconcileOutcome.UNKNOWN
        try:
            me = await getter()
            sender_id = int(getattr(me, "id"))
            messages = await self.telegram.get_messages(target, limit=HISTORY_SCAN_LIMIT)
        except asyncio.CancelledError:
            raise
        except Exception:
            return ReconcileOutcome.UNKNOWN
        if messages is None:
            return ReconcileOutcome.UNKNOWN

        now = time.time()
        eligible: list[Any] = []
        for message in messages:
            message_time = _timestamp(message)
            if message_time is None or not (
                started_at - CLOCK_SKEW_SECONDS <= message_time <= now + CLOCK_SKEW_SECONDS
            ):
                continue
            if getattr(message, "sender_id", None) != sender_id:
                continue
            if _message_caption(message) != caption:
                continue
            if _media_matches(_media_metadata(message), expected):
                eligible.append(message)

        external = evidence
        recorded_id = external.get("published_message_id")
        if recorded_id is not None:
            try:
                recorded_id = int(recorded_id)
            except (TypeError, ValueError):
                return ReconcileOutcome.UNKNOWN
            by_id = [message for message in messages if _message_id(message) == recorded_id]
            if len(by_id) == 1:
                message = by_id[0]
                message_time = _timestamp(message)
                if (message_time is not None
                        and started_at - CLOCK_SKEW_SECONDS <= message_time <= now + CLOCK_SKEW_SECONDS
                        and getattr(message, "sender_id", None) == sender_id
                        and _message_caption(message) == caption
                        and _media_matches(_media_metadata(message), expected)):
                    return ReconcileOutcome.HAPPENED
                return ReconcileOutcome.UNKNOWN
            # A recorded published-message ID is authoritative for identity.
            # If that ID is absent from the bounded history, do not substitute
            # a different caption/media match; the observation may be incomplete.
            return ReconcileOutcome.UNKNOWN

        if len(eligible) == 1:
            return ReconcileOutcome.HAPPENED
        if len(eligible) > 1:
            return ReconcileOutcome.UNKNOWN

        # NOT_HAPPENED requires a platform signal that publication was rejected,
        # plus a successful history observation with no matching publication.
        if bool(row["authoritative_rejection"]):
            return ReconcileOutcome.NOT_HAPPENED
        # A temporary upload handle describes an unobservable intermediate
        # operation, never a destination-visible published media message.
        return ReconcileOutcome.UNKNOWN
