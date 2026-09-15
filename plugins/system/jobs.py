"""Owner-facing durable job controls and interactive pagination."""

from __future__ import annotations

import re

from telethon import events

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from core.services.jobs import JobState
from helpers.hud import render
from helpers.ux import MAX_PAGE, PAGE_SIZE, confirmation_buttons, job_buttons, page_buttons, render_job, render_jobs

JOB_ID_RE = r"[0-9a-fA-F]{6,64}"
PATTERN = rf"^{re.escape(config.PREFIX)}job(?:\s+({JOB_ID_RE}))?$"
JOBS_PATTERN = rf"^{re.escape(config.PREFIX)}jobs(?:\s+(\d+))?$"
CANCEL_PATTERN = rf"^{re.escape(config.PREFIX)}cancel(?:\s+({JOB_ID_RE}))?$"
RETRY_PATTERN = rf"^{re.escape(config.PREFIX)}retry(?:\s+({JOB_ID_RE}))?$"


def _jobs():
    context = get_application_context()
    if context is None:
        raise CommandError("Application context is unavailable.")
    return context.get("jobs")


async def _resolve(job_id: str):
    jobs = _jobs()
    try:
        return await jobs.get(job_id)
    except KeyError:
        matches = [job for job in await jobs.list(limit=1000) if job.id.startswith(job_id.lower())]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CommandError(f"Job not found: `{job_id}`")
        raise CommandError(f"Job reference `{job_id}` is ambiguous; use more characters.")


async def _retry(job):
    if job.state not in {JobState.FAILED, JobState.CANCELLED}:
        raise CommandError(f"Only FAILED or CANCELLED jobs can be retried; current state is `{job.state}`.")
    jobs = _jobs()
    return await jobs.enqueue(
        job.type,
        dict(job.payload),
        owner=job.owner,
        parent_id=job.id,
        max_attempts=job.max_attempts,
        priority=job.priority,
        resource_class=job.resource_class,
        verify_required=job.verify_required,
    )


async def setup(client):
    register_cmd(client, pattern=PATTERN, handler=handle_job, category="system_ops", description="Show one durable job and its safe operator controls.")
    register_cmd(client, pattern=JOBS_PATTERN, handler=handle_jobs, category="system_ops", description="List durable jobs with bounded pagination.")
    register_cmd(client, pattern=CANCEL_PATTERN, handler=handle_cancel, category="system_ops", description="Cancel a durable job with explicit confirmation for active work.")
    register_cmd(client, pattern=RETRY_PATTERN, handler=handle_retry, category="system_ops", description="Manually retry a failed or cancelled durable job as a fresh run.")
    client.add_event_handler(handle_callback, events.CallbackQuery())


async def handle_job(event):
    job_id = (event.pattern_match.group(1) or "").strip()
    if not job_id:
        jobs = await _jobs().list(limit=PAGE_SIZE)
        has_next = len(jobs) == PAGE_SIZE
        await event.edit(render_jobs(jobs, 0, has_next=has_next), buttons=page_buttons("jobs", 0, has_next=has_next))
        return
    job = await _resolve(job_id)
    await event.edit(render_job(job), buttons=job_buttons(job.id, state=str(job.state)))


async def _jobs_page(event, page: int):
    page = max(0, min(page, MAX_PAGE))
    jobs = await _jobs().list(limit=(page + 1) * PAGE_SIZE + 1)
    start = page * PAGE_SIZE
    page_items = jobs[start:start + PAGE_SIZE]
    has_next = len(jobs) > start + PAGE_SIZE
    await event.edit(render_jobs(page_items, page, has_next=has_next), buttons=page_buttons("jobs", page, has_next=has_next))


async def handle_jobs(event):
    raw = (event.pattern_match.group(1) or "0").strip()
    page = int(raw) if raw else 0
    await _jobs_page(event, page)


async def handle_cancel(event):
    job_id = (event.pattern_match.group(1) or "").strip()
    if not job_id:
        raise CommandError(f"Usage: `{config.PREFIX}cancel <job-id>`")
    job = await _resolve(job_id)
    if job.state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.UNCERTAIN}:
        await event.edit(render_job(job, footer="system | job | already terminal"), buttons=job_buttons(job.id, state=str(job.state)))
        return
    await event.edit(render("CONFIRM CANCEL", [f"Job: `{job.id[:12]}`", f"State: `{job.state}`", "Cancellation of active work may become UNCERTAIN if external work was already in flight."], footer="system | confirmation"), buttons=confirmation_buttons("cancel", job.id))


async def handle_retry(event):
    job_id = (event.pattern_match.group(1) or "").strip()
    if not job_id:
        raise CommandError(f"Usage: `{config.PREFIX}retry <job-id>`")
    job = await _resolve(job_id)
    new_job = await _retry(job)
    await event.edit(render("JOB RETRIED", [f"Previous: `{job.id[:12]}`", f"New run: `{new_job.id[:12]}`", f"Type: `{new_job.type}`", "A fresh durable run was queued."], footer="system | JobEngine"), buttons=job_buttons(new_job.id, state=str(new_job.state)))


async def handle_callback(event):
    if event.sender_id != config.OWNER_ID:
        await event.answer("Not authorized", alert=True)
        return
    try:
        data = (event.data or b"").decode("utf-8", "strict")
        parts = data.split(":")
        if len(parts) < 3 or parts[0] != "ux":
            return
        if parts[1] == "jobs" and len(parts) == 4 and parts[2] == "page":
            await event.answer()
            await _jobs_page(event, int(parts[3]))
            return
        if parts[1] != "job" or len(parts) != 4:
            return
        action = parts[2]
        job = await _resolve(parts[3])
        if action == "status":
            await event.answer()
            await event.edit(render_job(job), buttons=job_buttons(job.id, state=str(job.state)))
        elif action == "confirm_cancel":
            await event.answer()
            await event.edit(render("CONFIRM CANCEL", [f"Job: `{job.id[:12]}`", f"State: `{job.state}`", "Confirm to cancel this durable job."], footer="system | confirmation"), buttons=confirmation_buttons("cancel", job.id))
        elif action == "cancel":
            await _jobs().cancel(job.id)
            refreshed = await _resolve(job.id)
            await event.answer("Cancellation requested")
            await event.edit(render_job(refreshed, footer="system | job | cancellation"), buttons=job_buttons(refreshed.id, state=str(refreshed.state)))
        elif action == "retry":
            new_job = await _retry(job)
            await event.answer("Retry queued")
            await event.edit(render("JOB RETRIED", [f"Previous: `{job.id[:12]}`", f"New run: `{new_job.id[:12]}`", f"Type: `{new_job.type}`"], footer="system | JobEngine"), buttons=job_buttons(new_job.id, state=str(new_job.state)))
    except CommandError as exc:
        await event.answer(str(exc), alert=True)
    except (ValueError, UnicodeError):
        await event.answer("Invalid job control", alert=True)
