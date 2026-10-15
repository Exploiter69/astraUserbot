"""Durable DELETE jobs with conservative exact-message reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import unicodedata
from typing import Any

from core.services.jobs import Job, JobEngine, JobError, ReconcileContext, ReconcileOutcome
from core.services.storage import StorageService

DELETE_JOB_TYPE = "DELETE"
DELETE_EFFECT_CLASS = "DELETE"


class AuthoritativeDeleteRejection(Exception):
    """Explicit evidence that a fake/platform DELETE request was not applied."""


def _canonical_state(message: Any) -> dict[str, Any]:
    text = getattr(message, "message", None)
    if text is None:
        text = getattr(message, "text", None)
    if text is None:
        text = getattr(message, "caption", None)
    return {
        "id": _message_id(message),
        "text": unicodedata.normalize(
            "NFC", str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        ),
        "sender_id": getattr(message, "sender_id", None),
        "date": str(getattr(message, "date", None)),
        "media_type": type(getattr(message, "media", None)).__name__
        if getattr(message, "media", None) is not None else None,
    }


def _fingerprint(message: Any) -> str:
    canonical = json.dumps(_canonical_state(message), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _message_id(message: Any) -> int | None:
    value = getattr(message, "id", getattr(message, "message_id", None))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _authoritative_rejection(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, AuthoritativeDeleteRejection):
            return True
        if (
            getattr(current, "authoritative_not_applied", False) is True
            and getattr(current, "retry_safe", False) is True
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class DeleteJobAdapter:
    """Register one DELETE handler and reconcile only its exact target message."""

    def __init__(self, jobs: JobEngine, telegram: Any, storage: StorageService) -> None:
        self.jobs = jobs
        self.telegram = telegram
        self.storage = storage
        if DELETE_JOB_TYPE not in jobs.handlers:
            jobs.register_handler(
                DELETE_JOB_TYPE,
                self.handle,
                effect_class=DELETE_EFFECT_CLASS,
                reconciler=self.reconcile,
            )

    async def _effect(self, job_id: str):
        rows = await self.storage.fetchall(
            "SELECT * FROM job_effects WHERE job_id=? AND effect_class=? AND required=1",
            (job_id, DELETE_EFFECT_CLASS),
        )
        if len(rows) != 1:
            raise JobError(
                "DELETE adapter requires exactly one required DELETE effect per job",
                code="DELETE_EFFECT_CARDINALITY",
            )
        return rows[0]

    async def _record_attempt(
        self, job: Job, target: Any, message_id: int, message: Any, started_at: float
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
                    json.dumps({"message_id": message_id, "pre_attempt_state": _canonical_state(message)},
                               separators=(",", ":"), ensure_ascii=False),
                    _fingerprint(message), started_at, time.time(),
                    job.id, DELETE_EFFECT_CLASS,
                ),
            )
            await self.storage.conn.commit()

    async def _record_rejection(self, job_id: str, error: BaseException) -> None:
        await self.storage.execute(
            """UPDATE job_effects SET authoritative_rejection=1, state='NOT_HAPPENED',
               reason=?, updated_at=? WHERE job_id=? AND effect_class=? AND required=1""",
            (f"AUTHORITATIVE_REJECTION:{type(error).__name__}"[:200], time.time(),
             job_id, DELETE_EFFECT_CLASS),
        )

    async def handle(self, job: Job) -> dict[str, Any]:
        target = job.payload.get("target", job.payload.get("peer_id"))
        raw_id = job.payload.get("message_id", job.payload.get("message"))
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError):
            message_id = 0
        if target is None or message_id <= 0:
            raise JobError(
                "DELETE payload requires target and positive message_id",
                code="DELETE_INVALID_PAYLOAD",
            )

        current = await self.telegram.get_messages(
            target, limit=2, min_id=message_id - 1, max_id=message_id + 1
        )
        exact = [item for item in current if _message_id(item) == message_id]
        if len(exact) != 1:
            # Never infer successful deletion from a missing or conflicting
            # pre-attempt observation; the target may be inaccessible.
            raise JobError("DELETE target is not uniquely accessible", code="DELETE_TARGET_UNKNOWN")
        started_at = time.time()
        await self._record_attempt(job, target, message_id, exact[0], started_at)
        try:
            await self.telegram.delete_messages(target, message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _authoritative_rejection(exc):
                await self._record_rejection(job.id, exc)
                raise JobError(
                    "Telegram authoritatively rejected the DELETE request",
                    code="DELETE_REJECTED", retryable=True,
                ) from exc
            raise JobError(
                "DELETE outcome is not authoritative",
                code="DELETE_OUTCOME_UNKNOWN", retryable=True,
            ) from exc
        return {"target": str(target), "message_id": message_id}

    async def reconcile(self, context: ReconcileContext) -> ReconcileOutcome:
        if context.effect_class != DELETE_EFFECT_CLASS:
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
            pre_state = evidence["pre_attempt_state"]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return ReconcileOutcome.UNKNOWN
        if (
            not row["payload_fingerprint"]
            or not isinstance(pre_state, dict)
            or pre_state.get("id") != message_id
        ):
            return ReconcileOutcome.UNKNOWN

        try:
            messages = await self.telegram.get_messages(
                target, limit=2, min_id=message_id - 1, max_id=message_id + 1
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return ReconcileOutcome.UNKNOWN
        exact = [item for item in messages if _message_id(item) == message_id]
        if len(exact) > 1:
            return ReconcileOutcome.UNKNOWN

        if not exact:
            # Absence only satisfies DELETE when the peer is still readable;
            # an empty result alone cannot distinguish deletion from lost access.
            capability_reader = getattr(self.telegram, "get_capabilities", None)
            if capability_reader is None:
                return ReconcileOutcome.UNKNOWN
            try:
                capabilities = await capability_reader(target, fresh=True)
            except TypeError:
                try:
                    capabilities = await capability_reader(target)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return ReconcileOutcome.UNKNOWN
            except asyncio.CancelledError:
                raise
            except Exception:
                return ReconcileOutcome.UNKNOWN
            if isinstance(capabilities, dict) and capabilities.get("can_read") is True:
                return ReconcileOutcome.HAPPENED
            return ReconcileOutcome.UNKNOWN

        observed_fingerprint = _fingerprint(exact[0])
        if bool(row["authoritative_rejection"]) and observed_fingerprint == row["payload_fingerprint"]:
            # Safe retry requires both authoritative non-application and a fresh
            # positive observation that the account can still delete in this peer.
            capability_reader = getattr(self.telegram, "get_capabilities", None)
            if capability_reader is None:
                return ReconcileOutcome.UNKNOWN
            try:
                capabilities = await capability_reader(target, fresh=True)
            except TypeError:
                try:
                    capabilities = await capability_reader(target)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return ReconcileOutcome.UNKNOWN
            except asyncio.CancelledError:
                raise
            except Exception:
                return ReconcileOutcome.UNKNOWN
            if isinstance(capabilities, dict) and capabilities.get("can_delete") is True:
                return ReconcileOutcome.NOT_HAPPENED
        # Existing but changed/conflicting state may reflect a different actor.
        return ReconcileOutcome.UNKNOWN
