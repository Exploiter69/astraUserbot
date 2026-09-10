import time
import asyncio

class ProgressCallback:
    def __init__(self, event, action: str = "Processing", edit_interval: float = 3.5):
        self.event = event
        self.action = action
        self.edit_interval = edit_interval
        self.last_edit = 0.0

    async def __call__(self, current: int, total: int):
        now = time.perf_counter()
        if (now - self.last_edit) >= self.edit_interval:
            percent = (current / total) * 100 if total else 0
            from helpers.hud import render
            try:
                await self.event.edit(render(
                    title="PROGRESS",
                    rows=[f"Task: {self.action}", f"Progress: {percent:.1f}%", f"Size: {current}/{total}"]
                ))
                self.last_edit = now
            except Exception:
                pass # Ignore FloodWait or MessageNotModified during progress edit
