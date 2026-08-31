# Self-Healing Web Service Agent — Technical Description

## 1. Overview
Self-Healing Web Service Agent is an autonomous recovery system for backend services. It continuously watches a running service, detects failure conditions from logs and metrics, uses a large language model to diagnose the root cause, selects a recovery action from a constrained, pre-approved action set, executes that action against live infrastructure, verifies the service returned to a healthy state, and records the full incident for audit. The system requires no human intervention during the detect-diagnose-recover-verify loop; a human only reviews the resulting log.

The target deployment surface is Google Cloud Run. The system does not attempt general-purpose infrastructure monitoring — it is scoped to a single service or small set of microservices, with a fixed, enumerable set of failure types and recovery actions, which keeps the agent's behavior predictable and safe to run autonomously.

## 2. Architecture

### 2.1 High-level components
The system is composed of three independently deployable services, communicating only through explicit, versioned message contracts:

1. **Target Service + Watcher** — the monitored application, plus a detection process that reads its logs/metrics and emits structured failure events.
2. **Diagnosis Agent** — a stateless decision service built on Gemini and Google's Agent Development Kit (ADK) that converts a failure event into a structured recovery decision.
3. **Orchestrator** — the central coordinator that receives failure events, invokes the diagnosis agent, executes the chosen recovery action against Cloud Run, verifies recovery, and persists the full incident history.

### 2.2 Data flow
```
Target Service (Cloud Run)
   │ structured JSON logs, metrics
   ▼
Watcher  ──publish──▶  Pub/Sub topic: failure-events
                                │
                                ▼
                        Orchestrator (Cloud Run)
                                │  invoke (HTTP or Pub/Sub)
                                ▼
                        Diagnosis Agent (Gemini + ADK)
                                │  structured decision
                                ▼
                        Orchestrator
                          │            │
                          ▼            ▼
                 Cloud Run Admin API   Firestore
                 (execute recovery)    (incident log)
                          │
                          ▼
                 Target Service (patched / rolled back / restarted)
                          │
                          ▼
                 Orchestrator polls health/error-rate → mark outcome
```

### 2.3 Communication contracts
All inter-service communication is JSON over Pub/Sub (or direct HTTPS for the diagnosis call), validated against two fixed schemas:

**Failure Event** (Watcher → Orchestrator)
- `service_id`, `revision_id`, `timestamp`
- `failure_type`: enum — `crash_loop`, `error_rate_spike`, `memory_leak`, `bad_deploy`, `health_check_failure`, `dependency_failure`
- `log_snippet`: last ~50 lines of structured logs
- `metrics`: `error_rate`, `memory_mb`, `restart_count`
- `last_known_good_revision`

**Recovery Decision** (Diagnosis Agent → Orchestrator)
- `service_id`, `diagnosed_cause`, `confidence`
- `chosen_action`: enum — `rollback_to_last_good`, `patch_env_var`, `increase_memory_limit`, `restart_instance`, `scale_down_instance`
- `action_params`: action-specific parameters (target revision, env key/value, memory limit, etc.)
- `reasoning`: short natural-language justification, stored for the audit log

Constraining `chosen_action` to a closed enum is a deliberate safety property: the diagnosis agent can reason freely, but it can never cause the orchestrator to execute an action outside a small, pre-vetted set.

## 3. Component Details

### 3.1 Target Service + Watcher
- The target is a small Flask/FastAPI application deployed on Cloud Run, instrumented to emit structured (JSON-line) logs for every request and error.
- It exposes debug-gated failure triggers used for testing and demonstration: an endpoint that raises repeated 500s, one that leaks memory until the container is OOM-killed, a deliberately broken revision for the bad-deploy scenario, and one that hangs past the readiness probe timeout.
- The Watcher is a separate lightweight process (a Cloud Run job or scheduled Cloud Function) that queries **Cloud Logging** and **Cloud Monitoring** for the target service, applying rule-based classifiers against each failure type (e.g., error-rate over threshold within a time window → `error_rate_spike`; container restart with OOM-kill signal → `memory_leak`; readiness probe failures exceeding a threshold → `health_check_failure`).
- On a positive classification, the Watcher constructs a Failure Event and publishes it to the `failure-events` Pub/Sub topic.

### 3.2 Diagnosis Agent
- Built with Google's Agent Development Kit (ADK), using Gemini 3.5 Flash as the underlying reasoning model.
- Receives a Failure Event and constructs a diagnosis prompt containing the failure type, log snippet, current metrics, and last known good revision.
- Uses ADK's structured output / function-calling capability to force the model's response into the exact Recovery Decision schema rather than parsing free text.
- A validation layer checks the returned `chosen_action` against the fixed enum and rejects (re-prompts, or falls back to a rule-based default) any response outside it — for example, `crash_loop` and `bad_deploy` default to `rollback_to_last_good` if the model's output fails validation, guaranteeing the loop never stalls or takes an unvetted action.
- The Diagnosis Agent is stateless and exposed as either a Cloud Run HTTP endpoint or a Pub/Sub subscriber, invoked once per failure event.

### 3.3 Orchestrator
- Runs as a Cloud Run service and is the only component with permission to modify the target service.
- Subscribes to `failure-events`, calls the Diagnosis Agent, and receives a Recovery Decision.
- Executes the decision against the live service using the **Cloud Run Admin API**:
  - `rollback_to_last_good` → shifts traffic to the specified prior revision.
  - `patch_env_var` → deploys a new revision with the corrected environment variable.
  - `increase_memory_limit` → updates the service's resource limits and redeploys.
  - `restart_instance` → forces a new revision deployment with unchanged config.
  - `scale_down_instance` → adjusts min/max instance counts.
- After executing the action, polls the service's health endpoint and error-rate metrics for a short verification window before marking the incident `recovered`, `failed`, or `escalated`.
- Persists every stage of the incident — the original failure event, the diagnosis, the action taken, and the verification result — to **Firestore**.

## 4. Data Model (Firestore)
- `services/{service_id}` — service-level status, current active revision, monitoring start time.
- `services/{service_id}/incidents/{incident_id}` — one document per incident, containing:
  - the full Failure Event
  - the full Recovery Decision (including model reasoning)
  - the action actually executed and its parameters
  - the verification result and final outcome
  - timestamps for each stage, enabling end-to-end latency measurement

This structure doubles as the source for the reporting layer — a simple dashboard or generated log reads directly from `incidents` to produce a human-readable narrative of each autonomous recovery (e.g., "error-rate spike detected → root cause: bad env var in latest revision → rolled back to last healthy revision → verified healthy after 30s").

## 5. Technology Stack
| Layer | Technology |
|---|---|
| Reasoning / diagnosis | Gemini 3.5 Flash, accessed via Google Agent Development Kit (ADK) |
| Compute | Google Cloud Run (target service + orchestrator + watcher) |
| Messaging | Google Cloud Pub/Sub (failure-events, recovery-decisions) |
| State / audit log | Google Firestore |
| Monitoring source | Google Cloud Logging, Google Cloud Monitoring |
| Infra control plane | Cloud Run Admin API (rollback, redeploy, scaling, resource limits) |
| Target application | Flask or FastAPI (Python) |

## 6. Safety Design
The system's safety properties come from constraining, not from trusting, the LLM:
- The action space available to the Diagnosis Agent is a small, fixed, human-reviewed enum — never free-form commands.
- Every action is validated before execution; invalid or out-of-scope actions fall back to a deterministic rule rather than being executed or silently dropped.
- Every recovery attempt is verified post-execution before being marked successful; a failed verification results in an `escalated` outcome rather than a further autonomous attempt, avoiding recovery loops.
- The orchestrator, not the diagnosis agent, holds infrastructure credentials — the LLM never has direct access to the Cloud Run Admin API.

## 7. Demonstration
The system is demonstrated end-to-end on a live Cloud Run deployment: a failure trigger is invoked on the target service (e.g., forcing a 500-error spike or deploying a broken revision), and the full pipeline — detection, diagnosis, action, verification, and logging — runs autonomously and observably, with the resulting Firestore incident record and dashboard shown as evidence of the recovery.

## 8. Future Extensions (beyond current scope)
- MCP-based tool integration in place of direct API calls, enabling the orchestrator to act across heterogeneous infrastructure providers through a common protocol.
- Additional monitoring sources (e.g., AWS CloudWatch) for multi-cloud coverage.
- PagerDuty integration for escalation when the agent cannot safely auto-recover.
- Slack integration for real-time incident notification and human-in-the-loop override during recovery.
