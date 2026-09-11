import re
import shutil
from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.reply import get_text_and_media
from helpers.progress import ProgressCallback
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}mediaflow(?:\s+(compress|extract|square|mute))?$"


async def setup(client):
    if not shutil.which("ffmpeg"):
        return
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_mediaflow,
        category="advanced",
        description="Advanced media transformation. Usage: .mediaflow [compress|extract|square|mute]"
    )


async def handle_mediaflow(event):
    mode = (event.pattern_match.group(1) or "compress").lower()
    _, media = await get_text_and_media(event)
    if not media:
        raise CommandError("Please reply to a video, audio, or GIF file.")

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    service = context.get("media")
    workspace = await service.create_workspace("mediaflow")

    try:
        in_file = await event.client.download_media(media, file=workspace.path)
        if not in_file:
            raise CommandError("Failed to download media file.")
        source = service.validate_input(in_file)

        await event.edit(render(
            title="MEDIAFLOW",
            rows=[f"Mode: {mode.upper()}", "Processing via FFmpeg..."],
            footer="advanced | mediaflow"
        ))

        if mode == "compress":
            options = ["-c:v", "libx264", "-crf", "26", "-preset", "fast", "-c:a", "aac", "-b:a", "128k"]
            output_name = "output.mp4"
        elif mode == "extract":
            options = ["-vn", "-c:a", "libmp3lame", "-b:a", "320k"]
            output_name = "output.mp3"
        elif mode == "square":
            options = ["-vf", r"crop=w=min(in_w\,in_h):h=min(in_w\,in_h)", "-c:v", "libx264", "-crf", "23", "-c:a", "copy"]
            output_name = "output.mp4"
        elif mode == "mute":
            options = ["-c:v", "libx264", "-crf", "23", "-preset", "fast", "-an"]
            output_name = "output.mp4"
        else:
            raise CommandError("Invalid mode. Use: compress, extract, square, or mute")

        await service.run_ffmpeg(
            workspace=workspace,
            input_path=source,
            output_name=output_name,
            options=options,
            timeout=300,
        )
        artifact = service.artifact(workspace, output_name)

        up_prog = ProgressCallback(event, f"Uploading ({mode})")
        await event.client.send_file(
            event.chat_id,
            file=artifact.path,
            progress_callback=up_prog,
            reply_to=event.reply_to_msg_id
        )
        await event.delete()
    finally:
        await service.cleanup(workspace)
