"""Durable SEND jobs with conservative Telegram history reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import unicodedata
from typing import Any

from telethon.errors import RPCError

from core.services.jobs import (
    Job,
    JobEngine,
    JobError,
    ReconcileContext,
    ReconcileOutcome,
)
from core.services.storage import StorageService

SEND_JOB_TYPE = "SEND"
SEND_EFFECT_CLASS = "SEND"
HISTORY_SCAN_LIMIT = 100
CLOCK_SKEW_SECONDS = 5.0


class AuthoritativeSendRejection(Exception):
    """Test/platform adapter signal that the attempted send was not accepted."""


def _normalized_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def send_fingerprint(target: Any, sender_id: int, text: Any) -> str:
    canonical = json.dumps(
        {
            "target": str(target).strip(),
            "sender_id": int(sender_id),
            "text": _normalized_text(text),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_authoritative_rejection(error: Exception) -> bool:
    if isinstance(error, (RPCError, AuthoritativeSendRejection)):
        return True
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RPCError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _message_id(message: Any) -> int | None:
    value = getattr(message, "id", None)
    if value is None:
        value = getattr(message, "message_id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _message_timestamp(message: Any) -> float | None:
    value = getattr(message, "date", None)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    timestamp = getattr(value, "timestamp", None)
    if callable(timestamp):
        try:
            return float(timestamp())
        except (TypeError, ValueError, OSError):
            return None
    return None


def _message_text(message: Any) -> str:
    value = getattr(message, "message", None)
    if value is None:
        value = getattr(message, "text", None)
    return _normalized_text(value)


class SendJobAdapter:
    """Register one SEND job handler and reconcile uncertain sends by observation."""

    def __init__(self, jobs: JobEngine, telegram: Any, storage: StorageService) -> None:
        self.jobs = jobs
        self.telegram = telegram
        self.storage = storage
        if SEND_JOB_TYPE not in self.jobs.handlers:
            self.jobs.register_handler(
                SEND_JOB_TYPE,
                self.handle,
                effect_class=SEND_EFFECT_CLASS,
                reconciler=self.reconcile,
            )

    async def _self_id(self) -> int | None:
        client = getattr(self.telegram, "client", None)
        getter = getattr(client, "get_me", None)
        if getter is None:
            getter = getattr(self.telegram, "get_me", None)
        if getter is None:
            return None
        try:
            me = await getter()
            value = getattr(me, "id", None)
            return int(value) if value is not None else None
        except Exception:
            return None

    async def _effect_ids(self, job_id: str) -> list[str]:
        rows = await self.storage.fetchall(
            "SELECT effect_id FROM job_effects WHERE job_id=? AND effect_class=? AND required=1 ORDER BY effect_id",
            (job_id, SEND_EFFECT_CLASS),
        )
        return [str(row["effect_id"]) for row in rows]

    async def _record_attempt(
        self, job: Job, target: Any, fingerprint: str | None, started_at: float
    ) -> None:
        target_json = json.dumps(target, separators=(",", ":"), ensure_ascii=False)
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute(
                """UPDATE job_effects
                   SET target_json=?, external_ref_json=NULL, payload_fingerprint=?,
                       attempt_started_at=?, authoritative_rejection=0,
                       state='PENDING', reason=NULL, updated_at=?
                   WHERE job_id=? AND effect_class=? AND required=1""",
                (
                    target_json,
                    fingerprint,
                    started_at,
                    time.time(),
                    job.id,
                    SEND_EFFECT_CLASS,
                ),
            )
            await self.storage.conn.commit()

    async def _record_external_ref(self, job_id: str, message_id: int | None) -> None:
        external_ref = {"message_id": message_id} if message_id is not None else {}
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute(
                """UPDATE job_effects
                   SET external_ref_json=?, state='HAPPENED', reason=NULL, updated_at=?
                   WHERE job_id=? AND effect_class=? AND required=1""",
                (
                    json.dumps(external_ref, separators=(",", ":")),
                    time.time(),
                    job_id,
                    SEND_EFFECT_CLASS,
                ),
            )
            await self.storage.conn.commit()

    async def _record_authoritative_rejection(self, job_id: str, error: Exception) -> None:
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute(
                """UPDATE job_effects
                   SET authoritative_rejection=1, state='NOT_HAPPENED',
                       reason=?, updated_at=?
                   WHERE job_id=? AND effect_class=? AND required=1""",
                (f"AUTHORITATIVE_REJECTION:{type(error).__name__}"[:200], time.time(), job_id, SEND_EFFECT_CLASS),
            )
            await self.storage.conn.commit()

    async def handle(self, job: Job) -> dict[str, Any]:
        target = job.payload.get("target", job.payload.get("peer_id"))
        text = job.payload.get("text", job.payload.get("message"))
        if target is None or not isinstance(text, str) or not text:
            raise JobError("SEND payload requires target and non-empty text", code="SEND_INVALID_PAYLOAD")

        started_at = time.time()
        sender_id = await self._self_id()
        fingerprint = send_fingerprint(target, sender_id, text) if sender_id is not None else None
        await self._record_attempt(job, target, fingerprint, started_at)

        try:
            sent = await self.telegram.send_message(target, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not _is_authoritative_rejection(exc):
                raise
            await self._record_authoritative_rejection(job.id, exc)
            raise JobError(
                "Telegram authoritatively rejected the SEND request",
                code="SEND_REJECTED",
                retryable=True,
            ) from exc

        message_id = _message_id(sent)
        await self._record_external_ref(job.id, message_id)
        return {"message_id": message_id, "target": str(target)}


    async def reconcile(self, context: ReconcileContext) -> ReconcileOutcome:
        # This adapter is intentionally SEND-only; other effect classes remain
        # UNKNOWN/default-deny even when the enclosing job is a SEND job.
        if context.effect_class != SEND_EFFECT_CLASS:
            return ReconcileOutcome.UNKNOWN
        row = await self.storage.fetchone(
            "SELECT authoritative_rejection, external_ref_json, payload_fingerprint, attempt_started_at, target_json "
            "FROM job_effects WHERE effect_id=?",
            (context.effect_id,),
        )
        if row is None:
            return ReconcileOutcome.UNKNOWN
        if bool(row["authoritative_rejection"]):
            return ReconcileOutcome.NOT_HAPPENED

        target = context.target
        if row["target_json"]:
            try:
                target = json.loads(row["target_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                return ReconcileOutcome.UNKNOWN
        if target is None:
            return ReconcileOutcome.UNKNOWN

        expected_fingerprint = row["payload_fingerprint"] or context.content_fingerprint
        started_at = row["attempt_started_at"] or context.attempt_started_at
        if not expected_fingerprint or started_at is None:
            return ReconcileOutcome.UNKNOWN
        try:
            external_ref = json.loads(row["external_ref_json"]) if row["external_ref_json"] else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return ReconcileOutcome.UNKNOWN
        recorded_id = external_ref.get("message_id") if isinstance(external_ref, dict) else None

        sender_id = await self._self_id()
        if sender_id is None:
            return ReconcileOutcome.UNKNOWN
        try:
            messages = await self.telegram.get_messages(target, limit=HISTORY_SCAN_LIMIT)
        except Exception:
            return ReconcileOutcome.UNKNOWN

        now = time.time()
        eligible: list[Any] = []
        for message in messages:
            message_time = _message_timestamp(message)
            if message_time is None:
                continue
            if message_time < float(started_at) - CLOCK_SKEW_SECONDS or message_time > now + CLOCK_SKEW_SECONDS:
                continue
            if getattr(message, "sender_id", None) != sender_id:
                continue
            candidate = send_fingerprint(target, sender_id, _message_text(message))
            if candidate == expected_fingerprint:
                eligible.append(message)

        if recorded_id is not None:
            try:
                recorded_id = int(recorded_id)
            except (TypeError, ValueError):
                return ReconcileOutcome.UNKNOWN
            matches_by_id = [message for message in messages if _message_id(message) == recorded_id]
            if len(matches_by_id) == 1:
                message = matches_by_id[0]
                message_time = _message_timestamp(message)
                if (
                    message_time is not None
                    and float(started_at) - CLOCK_SKEW_SECONDS <= message_time <= now + CLOCK_SKEW_SECONDS
                    and getattr(message, "sender_id", None) == sender_id
                    and send_fingerprint(target, sender_id, _message_text(message)) == expected_fingerprint
                ):
                    return ReconcileOutcome.HAPPENED
                return ReconcileOutcome.UNKNOWN

        if len(eligible) == 1:
            return ReconcileOutcome.HAPPENED
        return ReconcileOutcome.UNKNOWN
