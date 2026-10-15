"""Durable JOIN jobs with conservative membership reconciliation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from core.services.jobs import Job, JobEngine, JobError, ReconcileContext, ReconcileOutcome
from core.services.storage import StorageService

JOIN_JOB_TYPE = "JOIN"
JOIN_EFFECT_CLASS = "JOIN"
MEMBERSHIP_SCAN_LIMIT = 200


class AuthoritativeJoinRejection(Exception):
    """Explicit signal proving a join request was not accepted."""


def _id(value: Any) -> int | str | None:
    raw = getattr(value, "id", value)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return str(raw).strip() or None


def _participant_id(participant: Any) -> int | str | None:
    user = getattr(participant, "user", None)
    return _id(user if user is not None else participant)


def _authoritative_rejection(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, AuthoritativeJoinRejection):
            return True
        if (getattr(current, "authoritative_not_applied", False) is True
                and getattr(current, "retry_safe", False) is True):
            return True
        current = current.__cause__ or current.__context__
    return False


class JoinJobAdapter:
    """Register JOIN; never infer non-membership from a roster miss."""

    def __init__(self, jobs: JobEngine, telegram: Any, storage: StorageService) -> None:
        self.jobs = jobs
        self.telegram = telegram
        self.storage = storage
        if JOIN_JOB_TYPE not in jobs.handlers:
            jobs.register_handler(
                JOIN_JOB_TYPE, self.handle,
                effect_class=JOIN_EFFECT_CLASS, reconciler=self.reconcile,
            )

    async def _effect(self, job_id: str):
        rows = await self.storage.fetchall(
            "SELECT * FROM job_effects WHERE job_id=? AND effect_class=? AND required=1",
            (job_id, JOIN_EFFECT_CLASS),
        )
        if len(rows) != 1:
            raise JobError("JOIN adapter requires exactly one required JOIN effect",
                           code="JOIN_EFFECT_CARDINALITY")
        return rows[0]

    async def _record_attempt(self, job: Job, target: Any, started_at: float) -> None:
        await self._effect(job.id)
        fingerprint = hashlib.sha256(json.dumps(
            {"target": str(target).strip(), "kind": "channel_membership"},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        await self.storage.execute(
            """UPDATE job_effects
               SET target_json=?, external_ref_json=?, payload_fingerprint=?,
                   attempt_started_at=?, authoritative_rejection=0,
                   state='PENDING', reason=NULL, updated_at=?
               WHERE job_id=? AND effect_class=? AND required=1""",
            (json.dumps(target, separators=(",", ":"), ensure_ascii=False),
             json.dumps({"join_kind": "channel_membership"}, separators=(",", ":")),
             fingerprint, started_at, time.time(), job.id, JOIN_EFFECT_CLASS),
        )

    async def _record_rejection(self, job_id: str, error: BaseException) -> None:
        await self.storage.execute(
            """UPDATE job_effects SET authoritative_rejection=1, state='NOT_HAPPENED',
               reason=?, updated_at=? WHERE job_id=? AND effect_class=? AND required=1""",
            (f"AUTHORITATIVE_REJECTION:{type(error).__name__}"[:200], time.time(),
             job_id, JOIN_EFFECT_CLASS),
        )

    async def _membership_observation(self, target: Any) -> tuple[str, Any]:
        client = getattr(self.telegram, "client", None)
        if client is None:
            return "UNKNOWN", None
        try:
            entity = await self.telegram.get_entity(target)
            me_getter = getattr(client, "get_me", None)
            if me_getter is None:
                return "UNKNOWN", None
            me = await me_getter()
            me_id = _id(me)
            if me_id is None:
                return "UNKNOWN", None

            getter = getattr(self.telegram, "get_membership", None)
            if getter is not None:
                observed = await getter(entity)
                status = str(observed).upper()
                if observed is True or status in {"MEMBER", "PARTICIPANT", "ADMIN", "CREATOR"}:
                    return "MEMBER", observed
                if status in {"PENDING", "REQUESTED", "REQUEST_SENT"}:
                    return "PENDING", observed
                if observed is False or status in {"NON_MEMBER", "NOT_MEMBER"}:
                    request_getter = getattr(self.telegram, "get_join_request_status", None)
                    if request_getter is None:
                        # Without an explicit pending-request observation, a
                        # membership miss cannot safely authorize another join.
                        return "UNKNOWN", {"membership": observed, "request_status": "UNOBSERVED"}
                    request_status = await request_getter(entity)
                    request_text = str(request_status).upper()
                    if request_status is True or request_text in {"PENDING", "REQUESTED", "REQUEST_SENT"}:
                        return "PENDING", request_status
                    if request_status is False or request_text in {"NONE", "NO_REQUEST", "NOT_PENDING", "NO_PENDING_REQUEST"}:
                        return "NON_MEMBER", {"membership": observed, "request_status": request_status}
                    return "UNKNOWN", {"membership": observed, "request_status": request_status}
                return "UNKNOWN", observed

            participant_getter = getattr(client, "get_participants", None)
            if participant_getter is None:
                return "UNKNOWN", None
            participants = await participant_getter(entity, limit=MEMBERSHIP_SCAN_LIMIT)
            if participants is None:
                return "UNKNOWN", None
            ids = {_participant_id(item) for item in participants}
            if me_id in ids:
                return "MEMBER", {"participant_count": len(ids)}
            # Bounded roster miss is not authoritative non-membership.
            return "UNKNOWN", {"participant_count": len(ids), "membership_miss": True}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "joinrequestpending" in name or "requestpending" in name:
                return "PENDING", type(exc).__name__
            return "UNKNOWN", type(exc).__name__

    async def handle(self, job: Job) -> dict[str, Any]:
        target = job.payload.get("target", job.payload.get("channel", job.payload.get("peer_id")))
        if target is None or (isinstance(target, str) and not target.strip()):
            raise JobError("JOIN payload requires a target channel/group", code="JOIN_INVALID_PAYLOAD")
        started_at = time.time()
        await self._record_attempt(job, target, started_at)
        if isinstance(target, str) and any(token in target.lower() for token in ("joinchat/", "+", "t.me/")):
            raise JobError(
                "JOIN invite semantics are ambiguous",
                code="JOIN_INVITE_SEMANTICS_UNKNOWN",
                retryable=True,
            )
        client = getattr(self.telegram, "client", None)
        joiner = getattr(self.telegram, "join_channel", None) or getattr(client, "join_channel", None)
        try:
            if joiner is not None:
                await joiner(target)
            else:
                from telethon.tl.functions.channels import JoinChannelRequest
                if client is None:
                    raise RuntimeError("Telegram client unavailable")
                governed_call = getattr(self.telegram, "_call", None)
                if governed_call is not None:
                    from core.services.telegram_traffic import P1_INTERACTIVE, WRITE
                    await governed_call(
                        "__call__", JoinChannelRequest(target),
                        operation_class=WRITE, priority=P1_INTERACTIVE,
                    )
                else:
                    await client(JoinChannelRequest(target))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _authoritative_rejection(exc):
                await self._record_rejection(job.id, exc)
                raise JobError("Telegram authoritatively rejected JOIN",
                               code="JOIN_REJECTED", retryable=True) from exc
            raise JobError("JOIN outcome is not authoritative",
                           code="JOIN_OUTCOME_UNKNOWN", retryable=True) from exc
        return {"target": str(target), "join_requested": True}

    async def reconcile(self, context: ReconcileContext) -> ReconcileOutcome:
        if context.effect_class != JOIN_EFFECT_CLASS:
            return ReconcileOutcome.UNKNOWN
        row = await self.storage.fetchone(
            """SELECT target_json, external_ref_json, payload_fingerprint,
                      authoritative_rejection
               FROM job_effects WHERE effect_id=?""",
            (context.effect_id,),
        )
        if row is None or not row["target_json"] or not row["external_ref_json"] or not row["payload_fingerprint"]:
            return ReconcileOutcome.UNKNOWN
        try:
            target = json.loads(row["target_json"])
            evidence = json.loads(row["external_ref_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return ReconcileOutcome.UNKNOWN
        if target is None or not isinstance(evidence, dict) or evidence.get("join_kind") != "channel_membership":
            return ReconcileOutcome.UNKNOWN
        status, _observation = await self._membership_observation(target)
        if status == "MEMBER":
            return ReconcileOutcome.HAPPENED
        if status == "PENDING":
            return ReconcileOutcome.UNKNOWN
        if status == "NON_MEMBER" and bool(row["authoritative_rejection"]):
            return ReconcileOutcome.NOT_HAPPENED
        return ReconcileOutcome.UNKNOWN
