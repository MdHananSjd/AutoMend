import os
import psutil

class ServiceState:
    """Holds internal service state and metric flags for failure injection triggers."""

    def __init__(self) -> None:
        self.reset()

    def get_memory_usage_mb(self) -> int:
        """Returns current Resident Set Size (RSS) memory in Megabytes."""
        try:
            process = psutil.Process(os.getpid())
            return int(process.memory_info().rss / (1024 * 1024))
        except Exception:
            return 0

    def reset(self) -> None:
        """Clears all failure states and drops leaked memory."""
        self.is_healthy = True
        self.forced_error_rate = 0.0
        self.allocated_memory = []
        self.is_hanging = False
        self.is_error_spike = False

state = ServiceState()