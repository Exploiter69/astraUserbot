import re
import shutil
from core.context import get_application_context
from core.registry import register_cmd
from helpers.hud import render
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}rip(?:\s+(audio|video|doc|best))?(?:\s+(https?://\S+))?$"


async def setup(client):
    if not shutil.which("yt-dlp"):
        return
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_rip,
        category="media_ops",
        description="Universal stream and media extractor powered by yt-dlp.",
    )


async def handle_rip(event):
    mode = event.pattern_match.group(1) or "video"
    url = event.pattern_match.group(2)
    if not url:
        reply = await event.get_reply_message()
        if reply and reply.raw_text:
            match = re.search(r"https?://\S+", reply.raw_text)
            if match:
                url = match.group(0)
    if not url:
        raise CommandError(f"Usage: `{config.PREFIX}rip <audio|video|doc|best> <URL>`")

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    service = context.get("media")
    workspace = await service.create_workspace("rip")
    max_mb = max(1, service.max_output_bytes // (1024 * 1024))
    max_filesize = f"{max_mb}M"

    await event.edit(render("RIP // STREAM", [f"Mode: `{mode}`", f"Target: `{url}`", "Extracting stream..."]))
    if mode == "audio":
        argv = ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", "%(title).50s.%(ext)s", "--no-playlist", "--max-filesize", max_filesize, url]
    elif mode == "doc":
        argv = ["yt-dlp", "-f", "best", "-o", "%(title).50s.%(ext)s", "--no-playlist", "--max-filesize", max_filesize, url]
    elif mode == "best":
        argv = ["yt-dlp", "-f", "best", "-o", "%(title).50s.%(ext)s", "--no-playlist", "--max-filesize", max_filesize, url]
    else:
        argv = ["yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "-o", "%(title).50s.%(ext)s", "--no-playlist", "--max-filesize", max_filesize, url]

    try:
        _, artifacts = await service.run_download(argv, workspace=workspace, timeout=600)
        if len(artifacts) != 1:
            raise CommandError("yt-dlp produced an unexpected number of downloadable artifacts; refusing to upload an ambiguous result.")
        target = artifacts[0]
        await event.edit(render("RIP // UPLOADING", [f"File: `{target.path.name}`", "Uploading to chat..."]))
        await event.client.send_file(event.chat_id, file=str(target.path), caption=f"Extracted: `{target.path.name}`", reply_to=event.id)
        await event.delete()
    finally:
        await service.cleanup(workspace)