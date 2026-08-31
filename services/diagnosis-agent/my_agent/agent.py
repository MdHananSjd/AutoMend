from google.adk.agents.llm_agent import Agent
from pydantic import BaseModel, Field

from app.diagnose_service import SYSTEM_PROMPT


class ActionParams(BaseModel):
    """Fixed shape — must match REQUIRED_ACTION_PARAM_FIELDS in validation.py."""
    target_revision: str = ""
    env_key: str = ""
    env_value: str = ""
    memory_mb: int = 0


class RecoveryDecision(BaseModel):
    """Mirrors the frozen contract in §4.2 / §6.2 of the brief exactly.
    Field names and the chosen_action enum must not drift from validation.py
    — if you change one, change both and re-run the offline test suite.
    """

    service_id: str
    diagnosed_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    chosen_action: str = Field(
        description=(
            "MUST be exactly one of: rollback_to_last_good, patch_env_var, "
            "increase_memory_limit, restart_instance, scale_down_instance"
        )
    )
    action_params: ActionParams = Field(
        description="Set only the fields relevant to chosen_action; leave the rest at their defaults."
    )
    reasoning: str


root_agent = Agent(
    model="gemini-3.5-flash",
    name="diagnosis_agent",
    description=(
        "Diagnoses the root cause of a backend service failure from a "
        "structured Failure Event and selects one recovery action from a "
        "closed, pre-approved set."
    ),
    instruction=SYSTEM_PROMPT,
    output_schema=RecoveryDecision,
)