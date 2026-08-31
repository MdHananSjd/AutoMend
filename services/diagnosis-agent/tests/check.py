"""
One-off latency check for call_gemini(), not part of the test suite.
Run from diagnosis-agent/: python tests/check_latency.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gemini_client import call_gemini

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "failure_events.json").read_text())
event = FIXTURES["crash_loop"]

for i in range(5):
    start = time.monotonic()
    call_gemini(event)
    print(f"run {i}: {time.monotonic() - start:.2f}s")