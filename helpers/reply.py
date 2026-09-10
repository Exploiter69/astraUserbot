async def get_text_and_media(event):
    """Normalizes text/media extraction from command or replied message."""
    text = event.pattern_match.group(1) if event.pattern_match else None
    media = None
    
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if not text and reply_msg.text:
            text = reply_msg.text
        if reply_msg.media:
            media = reply_msg.media
            
    return text, media
