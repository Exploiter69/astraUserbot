import re
import shlex
from core.context import get_application_context
from core.registry import register_cmd
from helpers.hud import render
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}ff(?:\s+(.*))?$"


async def setup(client):
    register_cmd(client, pattern=PATTERN, handler=handle_ffmpeg, category="media", description="FFmpeg and FFprobe media processing workbench.")


async def handle_ffmpeg(event):
    raw_args = event.pattern_match.group(1) or ""
    reply = await event.get_reply_message()
    if not reply or not reply.media:
        raise CommandError("Please reply to an audio, video, or photo to process with FFmpeg.")

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    media = context.get("media")
    workspace = await media.create_workspace("ffmpeg")

    try:
        downloaded_path = await event.client.download_media(reply.media, file=workspace.path)
        if not downloaded_path:
            raise CommandError("Failed to download media file.")
        downloaded = media.validate_input(downloaded_path)
        try:
            user_args = shlex.split(raw_args) if raw_args.strip() else ["-c", "copy"]
        except ValueError as exc:
            raise CommandError("Malformed quotes in FFmpeg arguments.") from exc

        await event.edit(render("FFMPEG", ["Processing media stream with FFmpeg..."]))
        output_name = f"output{downloaded.suffix or '.mp4'}"
        await media.run_ffmpeg(
            workspace=workspace,
            input_path=downloaded,
            output_name=output_name,
            options=user_args,
            timeout=300,
        )
        artifact = media.artifact(workspace, output_name)

        await event.edit(render("FFMPEG", ["Uploading processed output..."]))
        await event.client.send_file(event.chat_id, file=str(artifact.path), caption=f"Processed with: `ffmpeg {' '.join(user_args)}`", reply_to=reply.id)
        await event.delete()
    finally:
        await media.cleanup(workspace)
