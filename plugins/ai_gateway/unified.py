"""Unified owner-facing AI command surface with bounded Telegram context."""

from __future__ import annotations

import re
import shutil

from config import config
from core.context import get_application_context
from core.errors import CommandError, ConfigurationError, ExternalServiceError, ResourceError, TimeoutError
from core.registry import register_cmd
from helpers.hud import render
from helpers.reply import get_text_and_media

_MAX_CONTEXT_MESSAGES = 32
_MAX_CONTEXT_CHARS = 24_000
_MAX_PROMPT_CHARS = 50_000
_MAX_INSTRUCTION_CHARS = 2_000
_MAX_DIAGNOSTIC_ROWS = 40

PATTERN = rf"^{re.escape(config.PREFIX)}ai(?:\s+(.*))?$"
EXPLAIN_PATTERN = rf"^{re.escape(config.PREFIX)}explain(?:\s+(.*))?$"
REWRITE_PATTERN = rf"^{re.escape(config.PREFIX)}rewrite(?:\s+(.*))?$"
TRANSLATE_PATTERN = rf"^{re.escape(config.PREFIX)}translate(?:\s+(.*))?$"
EXTRACT_PATTERN = rf"^{re.escape(config.PREFIX)}extract(?:\s+(.*))?$"
CODE_PATTERN = rf"^{re.escape(config.PREFIX)}code(?:\s+(.*))?$"
DIAG_PATTERN = rf"^{re.escape(config.PREFIX)}aidiag$"


def _context_limit(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        value = int(raw)
    except ValueError as exc:
        raise CommandError("Context message count must be an integer between 1 and 32.") from exc
    if not 1 <= value <= _MAX_CONTEXT_MESSAGES:
        raise CommandError("Context message count must be between 1 and 32.")
    return value


def _bounded_text(value: str, limit: int = _MAX_PROMPT_CHARS) -> str:
    text = str(value or "").strip()
    if not text:
        raise CommandError("Please provide text for the AI operation.")
    if len(text) > limit:
        raise ResourceError(f"AI text is limited to {limit:,} characters.")
    return text


def _reply_text(reply) -> str:
    return str(getattr(reply, "text", "") or "").strip()


async def _history_context(event, count: int) -> list[dict[str, str]]:
    if count <= 0:
        return []
    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    telegram = context.get("telegram")
    if telegram is None:
        raise CommandError("Telegram service is unavailable.")
    chat_id = getattr(event, "chat_id", None)
    if chat_id is None:
        raise CommandError("History context requires a Telegram chat.")
    messages = await telegram.get_messages(chat_id, limit=count)
    rows: list[dict[str, str]] = []
    total = 0
    for message in reversed(messages):
        text = _reply_text(message)
        if not text:
            continue
        sender = getattr(message, "sender_id", None)
        prefix = f"sender {sender}: " if sender is not None else "message: "
        piece = (prefix + text).strip()
        if total + len(piece) > _MAX_CONTEXT_CHARS:
            remaining = _MAX_CONTEXT_CHARS - total
            if remaining <= 0:
                break
            piece = piece[:remaining].rstrip()
        rows.append({"role": "user", "content": piece})
        total += len(piece)
        if total >= _MAX_CONTEXT_CHARS:
            break
    return rows


async def _reply_media_context(event, prompt: str) -> str | None:
    if not event.is_reply:
        return None
    _, media = await get_text_and_media(event)
    if not media:
        return None
    context = get_application_context()
    if context is None:
        raise CommandError("Required runtime services are unavailable.")
    media_service = context.get("media")
    ai = context.get("ai")
    if media_service is None or ai is None:
        raise CommandError("Required runtime services are unavailable.")
    mime = str(getattr(media, "mime_type", "") or "").lower()
    if mime.startswith("image/"):
        if not shutil.which("tesseract"):
            raise CommandError("Tesseract is unavailable for image-to-AI context.")
        workspace = await media_service.create_workspace("ai_ocr")
        try:
            downloaded = await media_service.download_telegram_media(event.client.download_media, media, workspace=workspace)
            if not downloaded:
                raise CommandError("Failed to download image media.")
            artifact = media_service.artifact(workspace, downloaded)
            result = await media_service.run_isolated(["tesseract", "/workspace/" + artifact.path.relative_to(workspace.path).as_posix(), "stdout", "-l", "eng"], workspace=workspace, timeout=60, max_output_bytes=512 * 1024)
            if result.returncode != 0:
                raise CommandError("Image OCR failed: " + (result.stderr.strip() or "unknown error"))
            text = result.stdout.strip()[:_MAX_CONTEXT_CHARS]
            return f"The replied image was OCR-extracted as:\n{text or '[no text detected]'}\n\nUser request:\n{prompt}"
        finally:
            await media_service.cleanup(workspace)
    if mime.startswith("audio/") or mime in {"application/ogg", "application/octet-stream"}:
        workspace = await media_service.create_workspace("ai_stt")
        try:
            downloaded = await media_service.download_telegram_media(event.client.download_media, media, workspace=workspace)
            if not downloaded:
                raise CommandError("Failed to download audio media.")
            artifact = media_service.artifact(workspace, downloaded)
            transcript = await ai.transcribe(artifact.path)
            text = transcript.text[:_MAX_CONTEXT_CHARS]
            return f"The replied audio was transcribed as:\n{text or '[no speech detected]'}\n\nUser request:\n{prompt}"
        finally:
            await media_service.cleanup(workspace)
    return None


async def _run_chat(event, prompt: str, *, title: str = "AI RESPONSE", system: str | None = None, history: int = 0) -> None:
    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    service = context.get("ai")
    if service is None:
        raise CommandError("AI service is unavailable.")
    prompt = _bounded_text(prompt)
    media_prompt = await _reply_media_context(event, prompt)
    if media_prompt:
        prompt = media_prompt
    elif event.is_reply:
        reply = await event.get_reply_message()
        reply_text = _reply_text(reply)
        if reply_text:
            reply_text = _bounded_text(reply_text, _MAX_CONTEXT_CHARS)
            prompt = f"Replied message context:\n{reply_text}\n\nUser request:\n{prompt}"
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system[:_MAX_INSTRUCTION_CHARS]})
    messages.extend(await _history_context(event, history))
    messages.append({"role": "user", "content": prompt})
    await event.edit(render(title="LLM INFERENCE", rows=[f"Routing to {service.provider_name}..."], footer="ai | unified"))
    try:
        response = await service.chat(messages)
    except (ConfigurationError, ExternalServiceError, ResourceError, TimeoutError) as exc:
        raise CommandError(str(exc)) from exc
    await event.edit(render(title=title, rows=response.text.splitlines() or [response.text], footer=f"ai | {response.provider}"))


async def setup(client):
    register_cmd(client, PATTERN, handle_ai, "ai", "Unified AI surface. Usage: .ai <prompt> or .ai --last N <prompt>.")
    register_cmd(client, EXPLAIN_PATTERN, handle_explain, "ai", "Explain text or a replied message with bounded AI context.")
    register_cmd(client, REWRITE_PATTERN, handle_rewrite, "ai", "Rewrite replied text or supplied text.")
    register_cmd(client, TRANSLATE_PATTERN, handle_translate, "ai", "Translate replied text or supplied text.")
    register_cmd(client, EXTRACT_PATTERN, handle_extract, "ai", "Extract requested information from replied text.")
    register_cmd(client, CODE_PATTERN, handle_code, "ai", "Use the AI gateway for bounded coding help.")
    register_cmd(client, DIAG_PATTERN, handle_diag, "ai", "Show non-sensitive AI provider, capability and budget diagnostics.")


async def handle_ai(event):
    args = (event.pattern_match.group(1) or "").strip()
    if not args:
        if event.is_reply:
            reply = await event.get_reply_message()
            args = _reply_text(reply)
        if not args:
            raise CommandError("Usage: `.ai <prompt>` or `.ai --last N <prompt>`. You may also reply to text/media.")
    history = 0
    match = re.match(r"^--last\s+(\d+)\s+(.+)$", args, flags=re.S)
    if match:
        history = _context_limit(match.group(1))
        args = match.group(2).strip()
    await _run_chat(event, args, history=history)


async def _text_target(event, supplied: str | None) -> str:
    if supplied and supplied.strip():
        return _bounded_text(supplied)
    if event.is_reply:
        reply = await event.get_reply_message()
        return _bounded_text(_reply_text(reply))
    raise CommandError("Provide text or reply to a text message.")


async def handle_explain(event):
    text = await _text_target(event, event.pattern_match.group(1))
    await _run_chat(event, text, title="EXPLANATION", system="Explain clearly, accurately, and at the user's apparent level. Do not invent facts.")


async def handle_rewrite(event):
    text = await _text_target(event, event.pattern_match.group(1))
    await _run_chat(event, f"Rewrite the following text while preserving its meaning and improving clarity:\n\n{text}", title="REWRITE")


async def handle_translate(event):
    text = await _text_target(event, event.pattern_match.group(1))
    await _run_chat(event, f"Translate the following text. If a target language is specified before a colon, use it; otherwise preserve the source language context:\n\n{text}", title="TRANSLATION")


async def handle_extract(event):
    instruction = (event.pattern_match.group(1) or "").strip()
    if len(instruction) > _MAX_INSTRUCTION_CHARS:
        raise ResourceError("Extraction instruction is too long.")
    text = await _text_target(event, None)
    context = get_application_context()
    service = context.get("ai") if context else None
    if service is None:
        raise CommandError("AI service is unavailable.")
    if not instruction:
        instruction = "Extract the key facts as concise bullet points."
    response = await service.extract(text, instruction)
    await event.edit(render(title="EXTRACTION", rows=response.text.splitlines() or [response.text], footer=f"ai | extract | {response.provider}"))


async def handle_code(event):
    prompt = await _text_target(event, event.pattern_match.group(1))
    await _run_chat(event, prompt, title="CODE ASSIST", system="You are a careful coding assistant. Prefer correct, minimal, actionable answers. Do not claim to have executed code you did not execute.")


async def handle_diag(event):
    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    service = context.get("ai")
    if service is None:
        raise CommandError("AI service is unavailable.")
    diagnostics = service.diagnostics
    rows = [f"Default provider: {diagnostics['provider']}", f"Remote enabled: {diagnostics['remote_enabled']}", f"Providers: {', '.join(diagnostics['providers'])}", f"Modes: {', '.join(f'{k}={v}' for k, v in diagnostics['modes'].items())}", f"Remote budget: {diagnostics['remote_requests_used']}/{diagnostics['remote_requests_limit']}", f"Budget remaining: {diagnostics['remote_requests_remaining']}", f"Window: {int(diagnostics['remote_window_seconds'])}s", f"Input cap: {diagnostics['max_input_chars']:,} chars", f"Output cap: {diagnostics['max_output_chars']:,} chars", f"Message cap: {diagnostics['max_message_count']} x {diagnostics['max_message_chars']:,} chars"][:_MAX_DIAGNOSTIC_ROWS]
    await event.edit(render(title="AI DIAGNOSTICS", rows=rows, footer="ai | diagnostics | no secrets"))
