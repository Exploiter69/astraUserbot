async def get_text_and_media(event):
    """Normalize text/media extraction from a command event or replied message."""
    text = None

    if event.pattern_match:
        try:
            text = event.pattern_match.group(1)
        except IndexError:
            # Some command patterns intentionally have no capture groups.
            text = None

    media = None

    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if not text and reply_msg.text:
            text = reply_msg.text
        if reply_msg.media:
            media = reply_msg.media

    return text, media
