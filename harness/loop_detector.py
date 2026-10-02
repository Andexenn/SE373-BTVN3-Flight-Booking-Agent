from collections import deque
from typing import Optional, Dict, Any


class LoopDetector:
    """Detection layer for infinite repetition and execution stagnation."""

    def __init__(self, window: int = 6, repeat_k: int = 2, stall_n: int = 4):
        self.window = window
        self.k = repeat_k
        self.n = stall_n
        self.recent = deque(maxlen=window)
        self.last_progress = None
        self.stall_count = 0

    def reset(self):
        """Reset the detector state."""
        self.recent.clear()
        self.last_progress = None
        self.stall_count = 0

    def check(self, tool_name: str, args: Dict[str, Any], progress_metric: Any = None) -> Optional[str]:
        """Check for repeated identical tool calls or stalled progress."""
        fingerprint = (tool_name, repr(sorted(args.items())))
        if self.recent.count(fingerprint) + 1 >= self.k:
            return "LOOP"
        self.recent.append(fingerprint)

        if progress_metric is not None:
            if progress_metric == self.last_progress:
                self.stall_count += 1
            else:
                self.stall_count = 0
                self.last_progress = progress_metric

            if self.stall_count >= self.n:
                return "STALL"

        return None
