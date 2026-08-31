"""
Wraps the ADK agent (my_agent/agent.py) as a plain synchronous function:

    call_gemini(failure_event: dict) -> dict

...which is exactly the `llm_call` shape that diagnose_service.diagnose()
expects. This is the ONLY file that talks to ADK/Gemini directly, and it's
the one part of this deliverable I have not been able to run — no network
in the sandbox this was built in, so google-adk was never actually
installed or exercised here. Everything upstream and downstream of this
function (validation, fallback, prompt building, the FastAPI endpoint) is
tested and green; this file needs a live smoke test in your own venv
before the demo. See tests/test_agent_live.py.

If ADK's Runner API in your installed version differs from what's below
(names/signatures do move between ADK releases), the fix is almost
certainly local to this function — diagnose_service.py doesn't need to
change since it only depends on the (dict) -> dict shape.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "my_agent" / ".env")

from my_agent.agent import root_agent

from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types


_APP_NAME = "automend_diagnosis_agent"
_USER_ID = "orchestrator"


async def _run_once(prompt: str) -> str:
    """Runs the agent for a single turn and returns the final response text.
    A fresh session per call — the agent is stateless per the brief
    ("Agent is stateless and invoked once per failure event")."""
    runner = InMemoryRunner(agent=root_agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID
    )
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)])

    final_text = ""
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=session.id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)

    return final_text


def call_gemini(failure_event: dict[str, Any]) -> dict[str, Any]:
    """Synchronous entry point used by diagnose_service.diagnose().

    diagnose() already runs this inside its own thread + timeout, so we
    don't need our own timeout handling here — just do the call and let
    exceptions propagate (diagnose() catches them and falls back).
    """
    from app.diagnose_service import build_prompt  # local import avoids a cycle

    prompt = build_prompt(failure_event)
    raw_text = asyncio.run(_run_once(prompt))

    # With output_schema set on the agent, ADK should hand back clean JSON
    # text. We still parse defensively — if a stray code fence or leading/
    # trailing text slips through, validate_recovery_decision() will still
    # catch a bad shape and fall back, but a clean parse here means the
    # model's actual (valid) decision gets used instead of being wasted.
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    return json.loads(text)  # noqa: this may raise; caller (diagnose) catches it
