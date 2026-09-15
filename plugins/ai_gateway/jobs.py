"""Durable AI jobs backed by the shared JobEngine."""

from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError, ConfigurationError, ExternalServiceError, ResourceError, TimeoutError
from core.registry import register_cmd
from helpers.hud import render
from helpers.ux import job_buttons

_MAX_PROMPT = 50_000
PATTERN = rf"^{re.escape(config.PREFIX)}aijob(?:\s+(.*))?$"


def _prompt(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        raise CommandError("Usage: `.aijob <prompt>`")
    if len(text) > _MAX_PROMPT:
        raise ResourceError(f"AI job prompt is limited to {_MAX_PROMPT:,} characters.")
    return text


async def _handle_ai_chat(job):
    context = get_application_context()
    if context is None:
        raise RuntimeError("Application context is unavailable")
    service = context.get("ai")
    if service is None:
        raise RuntimeError("AI service is unavailable")
    prompt = _prompt(job.payload.get("prompt"))
    await context.get("jobs").update_progress(job.id, 0.1)
    try:
        response = await service.chat([{"role": "user", "content": prompt}])
    except (ConfigurationError, ExternalServiceError, ResourceError, TimeoutError) as exc:
        from core.services.jobs import JobError
        raise JobError(str(exc), code="AI_REQUEST_FAILED", retryable=isinstance(exc, (ExternalServiceError, TimeoutError))) from exc
    await context.get("jobs").update_progress(job.id, 0.9)
    return {"text": response.text, "provider": response.provider, "model": response.model, "input_chars": response.input_chars, "output_chars": response.output_chars}


async def setup(client):
    context = get_application_context()
    if context is None:
        return
    jobs = context.get("jobs")
    if "AI_CHAT" not in jobs.handlers:
        jobs.register_handler("AI_CHAT", _handle_ai_chat)
    register_cmd(client, PATTERN, handle_aijob, "ai", "Queue a durable AI chat job. Usage: .aijob <prompt>")


async def handle_aijob(event):
    prompt = _prompt(event.pattern_match.group(1))
    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    jobs = context.get("jobs")
    await event.edit(render(title="AI JOB", rows=["Queueing durable AI work..."], footer="ai | durable job"))
    job = await jobs.enqueue(
        "AI_CHAT",
        {"prompt": prompt},
        owner=str(config.OWNER_ID),
        max_attempts=3,
        priority=0,
        resource_class="ai",
    )
    await event.edit(
        render(
            title="AI JOB QUEUED",
            rows=[f"ID: `{job.id[:12]}`", "State: QUEUED", "Use `.job <id>` for status."],
            footer="ai | durable | resumable",
        ),
        buttons=job_buttons(job.id, job.state),
    )
