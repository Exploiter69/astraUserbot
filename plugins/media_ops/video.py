import re
from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.reply import get_text_and_media
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(round|ss|compress|reverse)(?:\s+(.*))?$"


async def setup(client):
    register_cmd(client, PATTERN, handle_video, "media_ops", "Advanced video manipulation (FFmpeg).")


async def handle_video(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)
    _, media = await get_text_and_media(event)
    if not media:
        raise CommandError("Reply to a video/GIF.")

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    service = context.get("media")
    workspace = await service.create_workspace("video")

    try:
        in_file = await event.client.download_media(media, file=workspace.path)
        if not in_file:
            raise CommandError("Failed to download media.")
        source = service.validate_input(in_file)

        await event.edit(render("VIDEO OPS", [f"Operation: {cmd.upper()}", "Processing (Media Service)..."]))

        if cmd == "round":
            output_name = "output.mp4"
            options = ["-vf", r"crop=w=min(in_w\,in_h):h=min(in_w\,in_h),scale=512:512", "-c:v", "libx264", "-crf", "24", "-an"]
        elif cmd == "ss":
            sec = arg or "00:00:01"
            if len(sec) > 32 or any(ch not in "0123456789:." for ch in sec):
                raise CommandError("Invalid screenshot timestamp.")
            output_name = "output.jpg"
            options = ["-ss", sec, "-frames:v", "1", "-q:v", "2"]
        elif cmd == "compress":
            output_name = "output.mp4"
            options = ["-c:v", "libx264", "-crf", "28", "-preset", "fast", "-c:a", "aac", "-b:a", "128k"]
        elif cmd == "reverse":
            output_name = "output.mp4"
            options = ["-vf", "reverse", "-af", "areverse"]
        else:
            raise CommandError("Unsupported video operation.")

        await service.run_ffmpeg(
            workspace=workspace,
            input_path=source,
            output_name=output_name,
            options=options,
            timeout=300,
        )
        artifact = service.artifact(workspace, output_name)
        await event.client.send_file(
            event.chat_id,
            file=artifact.path,
            video_note=(cmd == "round"),
            reply_to=event.reply_to_msg_id,
        )
        await event.delete()
    finally:
        await service.cleanup(workspace)
