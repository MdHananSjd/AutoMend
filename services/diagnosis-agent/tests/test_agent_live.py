"""
LIVE smoke test — actually calls Gemini via ADK. Needs GOOGLE_API_KEY (or
Vertex credentials) set and network access, so it was NOT run by Claude
while building this (sandboxed, no network, no ADK installed).

Run this yourself once, before the demo, from diagnosis-agent/:
    pip install -r requirements.txt
    export GOOGLE_API_KEY=...          # or source your .env
    python3 tests/test_agent_live.py

This is deliberately separate from test_diagnose_offline.py: offline tests
prove the validation/fallback logic is correct; this proves the actual
model+ADK wiring in agent.py/gemini_client.py works end to end against your
installed ADK version, since that part was written but not executable in
the sandbox this was built in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "failure_events.json").read_text())

print("Calling real Gemini via ADK for a hand-crafted crash_loop event...")
print("(If this hangs or errors, see the NOTE FOR YOU comments in")
print(" my_agent/agent.py and app/gemini_client.py first.)\n")

try:
    from app.gemini_client import call_gemini
except Exception as exc:  # noqa: BLE001
    print(f"IMPORT FAILED: {exc}")
    print("Likely means the ADK API surface in your installed version")
    print("differs from what gemini_client.py/agent.py assume. Check:")
    print("  - output_schema= kwarg name on Agent(...)")
    print("  - InMemoryRunner / runner.run_async signature")
    sys.exit(1)

event = FIXTURES["crash_loop"]

try:
    raw = call_gemini(event)
except Exception as exc:  # noqa: BLE001
    print(f"CALL FAILED: {exc!r}")
    sys.exit(1)

print("Raw model output:")
print(json.dumps(raw, indent=2))

from app.validation import CHOSEN_ACTIONS, validate_recovery_decision  # noqa: E402

decision, fallback_used, reason = validate_recovery_decision(raw, event)
print("\nAfter validation:")
print(json.dumps(decision, indent=2))

assert decision["chosen_action"] in CHOSEN_ACTIONS
if fallback_used:
    print(f"\nNOTE: fell back to a deterministic action (reason={reason}).")
    print("The model's raw output above didn't pass validation as-is —")
    print("worth checking whether output_schema is actually being enforced.")
else:
    print("\nModel output passed validation directly. Wiring looks good.")

print("\nNow run this same check through the full pipeline (with the")
print("built-in timeout) via diagnose():")

from app.diagnose_service import diagnose  # noqa: E402
from app.gemini_client import call_gemini as _call  # noqa: E402

full_decision = diagnose(event, _call)
print(json.dumps(full_decision, indent=2))
