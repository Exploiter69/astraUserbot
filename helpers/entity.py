from telethon import types
from core.errors import CommandError

async def resolve_target(event) -> types.User | types.Chat:
    """Resolves target from reply, mention/ID arg, or defaults to self."""
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        return await event.client.get_entity(reply_msg.sender_id)
        
    if event.pattern_match:
        args = event.pattern_match.group(1)
        if args:
            target_str = args.split()[0]
            try:
                # Try to parse as int ID if possible
                target = int(target_str) if target_str.lstrip('-').isdigit() else target_str
                return await event.client.get_entity(target)
            except (ValueError, TypeError):
                pass
            except Exception as e:
                raise CommandError(f"Could not resolve entity: {target_str}")
                
    return await event.client.get_entity("me")
