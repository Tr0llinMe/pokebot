from collections import defaultdict
from typing import Dict, Tuple
from datetime import datetime

class RateLimiter:
    def __init__(self, rate: int, per: float):
        self.rate = rate  # Number of allowed commands
        self.per = per   # Time window in seconds
        self.tokens = defaultdict(lambda: self.rate)
        self.last_update = defaultdict(float)

    def is_rate_limited(self, user_id: int) -> Tuple[bool, float]:
        current = datetime.now().timestamp()
        time_passed = current - self.last_update[user_id]
        
        # Reset tokens if enough time has passed
        if time_passed > self.per:
            self.tokens[user_id] = self.rate
        
        # Update last check time
        self.last_update[user_id] = current
        
        if self.tokens[user_id] <= 0:
            return True, self.per - time_passed
        
        self.tokens[user_id] -= 1
        return False, 0 