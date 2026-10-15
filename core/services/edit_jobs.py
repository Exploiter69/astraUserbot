"""Durable EDIT jobs with conservative exact-message reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import unicodedata
from typing import Any

from telethon.errors import RPCError

from core.services.jobs import Job, JobEngine, JobError, ReconcileContext, ReconcileOutcome
from core.services.storage import StorageService

EDIT_JOB_TYPE = "EDIT"
EDIT_EFFECT_CLASS = "EDIT"


class AuthoritativeEditRejection(Exception):
    """Fake/platform signal that the edit was rejected before application."""


def _canonical_text(value: Any) -> str:
    return unicodedata.normalize(
        "NFC", str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    )


def _state_fingerprint(text: Any) -> str:
    return hashlib.sha256(_canonical_text(text).encode("utf-8")).hexdigest()


def _message_id(message: Any) -> int | None:
    value = getattr(message, "id", getattr(message, "message_id", None))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _message_text(message: Any) -> str:
    value = getattr(message, "message", None)
    if value is None:
        value = getattr(message, "text", None)
    if value is None:
        value = getattr(message, "caption", None)
    return _canonical_text(value)


def _authoritative_rejection(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        # Only an explicit adapter signal (or an exception that declares both
        # properties) proves non-application and permits a safe retry. A generic
        # RPC error can mean permissions/rate limits changed and is not enough.
        if isinstance(current, AuthoritativeEditRejection):
            return True
        if (
            getattr(current, "authoritative_not_applied", False) is True
            and getattr(current, "retry_safe", False) is True
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class EditJobAdapter:
    """Register one EDIT handler and reconcile only its exact target message."""

    def __init__(self, jobs: JobEngine, telegram: Any, storage: StorageService) -> None:
        self.jobs = jobs
        self.telegram = telegram
        self.storage = storage
        if EDIT_JOB_TYPE not in jobs.handlers:
            jobs.register_handler(
                EDIT_JOB_TYPE,
                self.handle,
                effect_class=EDIT_EFFECT_CLASS,
                reconciler=self.reconcile,
            )

    async def _effect(self, job_id: str):
        rows = await self.storage.fetchall(
            "SELECT * FROM job_effects WHERE job_id=? AND effect_class=? AND required=1",
            (job_id, EDIT_EFFECT_CLASS),
        )
        if len(rows) != 1:
            raise JobError(
                "EDIT adapter requires exactly one required EDIT effect per job",
                code="EDIT_EFFECT_CARDINALITY",
            )
        return rows[0]

    async def _record_attempt(
        self, job: Job, target: Any, message_id: int, intended_text: str,
        baseline_text: str, started_at: float,
    ) -> None:
        await self._effect(job.id)
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute(
                """UPDATE job_effects
                   SET target_json=?, external_ref_json=?, payload_fingerprint=?,
                       attempt_started_at=?, authoritative_rejection=0,
                       state='PENDING', reason=NULL, updated_at=?
                   WHERE job_id=? AND effect_class=? AND required=1""",
                (
                    json.dumps(target, separators=(",", ":"), ensure_ascii=False),
                    json.dumps({"message_id": message_id, "baseline_text": baseline_text},
                               separators=(",", ":"), ensure_ascii=False),
                    _state_fingerprint(intended_text), started_at, time.time(),
                    job.id, EDIT_EFFECT_CLASS,
                ),
            )
            await self.storage.conn.commit()

    async def _record_rejection(self, job_id: str, error: BaseException) -> None:
        await self.storage.execute(
            """UPDATE job_effects SET authoritative_rejection=1, state='NOT_HAPPENED',
               reason=?, updated_at=? WHERE job_id=? AND effect_class=? AND required=1""",
            (f"AUTHORITATIVE_REJECTION:{type(error).__name__}"[:200], time.time(),
             job_id, EDIT_EFFECT_CLASS),
        )

    async def handle(self, job: Job) -> dict[str, Any]:
        target = job.payload.get("target", job.payload.get("peer_id"))
        raw_id = job.payload.get("message_id", job.payload.get("message"))
        intended_text = job.payload.get("text", job.payload.get("caption"))
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError):
            message_id = 0
        if target is None or message_id <= 0 or not isinstance(intended_text, str):
            raise JobError(
                "EDIT payload requires target, positive message_id and text/caption",
                code="EDIT_INVALID_PAYLOAD",
            )

        # Capture the exact current state before mutation. If the operation is
        # later rejected, this baseline is required before NOT_HAPPENED is safe.
        current = await self.telegram.get_messages(
            target, limit=1, min_id=message_id - 1, max_id=message_id + 1
        )
        exact = [item for item in current if _message_id(item) == message_id]
        if len(exact) != 1:
            raise JobError("EDIT target message is not uniquely accessible", code="EDIT_TARGET_UNKNOWN")
        baseline_text = _message_text(exact[0])
        started_at = time.time()
        await self._record_attempt(
            job, target, message_id, intended_text, baseline_text, started_at
        )
        try:
            await self.telegram.edit_message(target, message_id, intended_text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _authoritative_rejection(exc):
                await self._record_rejection(job.id, exc)
                raise JobError(
                    "Telegram authoritatively rejected the EDIT request",
                    code="EDIT_REJECTED", retryable=True,
                ) from exc
            # Keep ambiguous transport failures in UNCERTAIN through the normal
            # declared-effect retry gate; never make them terminal/replayable.
            raise JobError(
                "EDIT outcome is not authoritative",
                code="EDIT_OUTCOME_UNKNOWN", retryable=True,
            ) from exc
        return {"target": str(target), "message_id": message_id}

    async def reconcile(self, context: ReconcileContext) -> ReconcileOutcome:
        if context.effect_class != EDIT_EFFECT_CLASS:
            return ReconcileOutcome.UNKNOWN
        row = await self.storage.fetchone(
            """SELECT target_json, external_ref_json, payload_fingerprint,
                      authoritative_rejection
               FROM job_effects WHERE effect_id=?""",
            (context.effect_id,),
        )
        if row is None or not row["target_json"] or not row["external_ref_json"]:
            return ReconcileOutcome.UNKNOWN
        try:
            target = json.loads(row["target_json"])
            evidence = json.loads(row["external_ref_json"])
            message_id = int(evidence["message_id"])
            baseline_text = evidence["baseline_text"]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return ReconcileOutcome.UNKNOWN
        if not row["payload_fingerprint"]:
            return ReconcileOutcome.UNKNOWN

        try:
            messages = await self.telegram.get_messages(
                target, limit=1, min_id=message_id - 1, max_id=message_id + 1
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return ReconcileOutcome.UNKNOWN
        exact = [item for item in messages if _message_id(item) == message_id]
        if len(exact) != 1:
            # Deleted/inaccessible is not evidence that an edit never applied.
            return ReconcileOutcome.UNKNOWN
        observed = _message_text(exact[0])
        if _state_fingerprint(observed) == row["payload_fingerprint"]:
            return ReconcileOutcome.HAPPENED
        if bool(row["authoritative_rejection"]) and observed == _canonical_text(baseline_text):
            return ReconcileOutcome.NOT_HAPPENED
        # A different state may be a later edit by another actor.
        return ReconcileOutcome.UNKNOWN
