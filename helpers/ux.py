"""Shared Telegram interaction primitives for durable Astra workflows."""

from __future__ import annotations

from typing import Iterable

from telethon import Button

from helpers.hud import render

PAGE_SIZE = 6
MAX_PAGE = 100


def progress_bar(progress: float, width: int = 10) -> str:
    """Return a bounded text progress bar."""
    value = max(0.0, min(1.0, float(progress)))
    filled = min(width, max(0, round(value * width)))
    return "[" + "█" * filled + "·" * (width - filled) + "]"


def job_buttons(job_id: str, *, state: str) -> list[list[Button]]:
    """Build compact controls; callbacks carry only a bounded job identifier."""
    buttons: list[Button] = [Button.inline("↻ Status", f"ux:job:status:{job_id}".encode())]
    if state in {"QUEUED", "RUNNING", "VERIFYING", "PAUSED"}:
        buttons.append(Button.inline("■ Cancel", f"ux:job:confirm_cancel:{job_id}".encode()))
    if state in {"FAILED", "CANCELLED"}:
        buttons.append(Button.inline("↺ Retry", f"ux:job:retry:{job_id}".encode()))
    return [buttons]


def confirmation_buttons(action: str, job_id: str) -> list[list[Button]]:
    return [[
        Button.inline("Confirm", f"ux:job:{action}:{job_id}".encode()),
        Button.inline("Keep", f"ux:job:status:{job_id}".encode()),
    ]]


def page_buttons(kind: str, page: int, *, has_next: bool) -> list[list[Button]]:
    row: list[Button] = []
    if page > 0:
        row.append(Button.inline("‹ Prev", f"ux:{kind}:page:{page - 1}".encode()))
    if has_next:
        row.append(Button.inline("Next ›", f"ux:{kind}:page:{page + 1}".encode()))
    return [row] if row else []


def render_job(job, *, footer: str = "system | job") -> str:
    """Canonical durable-job operator card."""
    percent = max(0.0, min(100.0, float(job.progress) * 100.0))
    rows = [
        f"Job: `{job.id[:12]}`",
        f"Type: `{job.type}`",
        f"State: `{job.state}`",
        f"Progress: {progress_bar(job.progress)} {percent:.0f}%",
        f"Attempt: {job.attempt_count}/{job.max_attempts}",
        f"Priority: P{job.priority}  ·  resource: {job.resource_class}",
    ]
    if job.error_code:
        rows.extend(["---", f"Error: `{job.error_code}`", job.error_message or "No further error detail."])
    return render("JOB", rows, footer=footer)


def render_jobs(jobs: Iterable, page: int, *, has_next: bool) -> str:
    rows = [f"Page: {page + 1}", "---"]
    for job in jobs:
        percent = max(0.0, min(100.0, float(job.progress) * 100.0))
        rows.append(f"`{job.id[:12]}`  {job.type}  {job.state}  {percent:.0f}%")
    if len(rows) == 2:
        rows.append("No jobs on this page.")
    return render("JOBS", rows, footer="system | jobs")
