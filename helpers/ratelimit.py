import time
from collections import deque
from core.errors import CommandError

class RateLimiter:
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.history = {}

    def check(self, user_id: int):
        now = time.perf_counter()
        if user_id not in self.history:
            self.history[user_id] = deque(maxlen=self.max_calls)
            
        history = self.history[user_id]
        
        while history and history[0] <= now - self.time_window:
            history.popleft()
            
        if len(history) >= self.max_calls:
            raise CommandError("Rate limit exceeded. Please wait.")
            
        history.append(now)
