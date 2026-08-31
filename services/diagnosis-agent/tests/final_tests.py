"""
One-off live smoke test across all six failure types. Confirms real Gemini
output validates cleanly (no fallback) for each failure_type, and reports
latency per type. Not collected by pytest (doesn't start with test_) —
run by hand, needs GOOGLE_API_KEY and network.

Run from services/diagnosis-agent/: python tests/check_all_types_live.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gemini_client import call_gemini
from app.diagnose_service import diagnose
from app.validation import CHOSEN_ACTIONS, validate_recovery_decision

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "failure_events.json").read_text())

results = []

for failure_type, event in FIXTURES.items():
    print("=" * 70)
    print(f"failure_type: {failure_type}")
    print("=" * 70)

    start = time.monotonic()
    try:
        raw = call_gemini(event)
    except Exception as exc:  # noqa: BLE001
        print(f"  CALL FAILED: {exc!r}")
        results.append((failure_type, None, None, False, "call_failed"))
        continue
    elapsed = time.monotonic() - start

    decision, fallback_used, reason = validate_recovery_decision(raw, event)

    print(f"  latency: {elapsed:.2f}s")
    print(f"  chosen_action: {decision['chosen_action']}")
    print(f"  confidence: {decision['confidence']}")
    print(f"  fallback_used: {fallback_used}" + (f" ({reason})" if reason else ""))
    print()

    results.append((failure_type, elapsed, decision["chosen_action"], fallback_used, reason))

print("=" * 70)
print("SUMMARY")
print("=" * 70)
ok = True
for failure_type, elapsed, action, fallback_used, reason in results:
    if elapsed is None:
        print(f"  {failure_type:25s} FAILED TO CALL")
        ok = False
        continue
    status = "FALLBACK" if fallback_used else "OK"
    if fallback_used:
        ok = False
    print(f"  {failure_type:25s} {elapsed:5.2f}s  {action:25s} {status}")

if not ok:
    print("\nNOTE: at least one failure_type used the deterministic fallback")
    print("instead of a validated model response — check the reason above.")

print("\nAlso confirming the full diagnose() pipeline doesn't time out on")
print("any type given current LLM_CALL_TIMEOUT_SECONDS...")
for failure_type, event in FIXTURES.items():
    full = diagnose(event, call_gemini)
    tag = "FALLBACK" if full["reasoning"].startswith("[deterministic fallback") else "OK"
    print(f"  {failure_type:25s} {tag}")