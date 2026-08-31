# Self-Healing Web Service Agent — PRD & 2-Day Build Plan

## 1. Problem Statement
Backend services fail in recurring, diagnosable ways — crash loops, 5xx error spikes, memory leaks/OOM, bad deploys, broken config/env vars, downstream dependency failures. Today, recovery means an engineer gets paged, reads logs/metrics, figures out the cause, and manually rolls back or patches the service. This is slow and doesn't scale with the number of services running.

## 2. Proposed Solution
An autonomous agent that watches a running backend service (or small set of microservices) on Cloud Run, detects failure from logs/metrics, diagnoses root cause with Gemini, picks a recovery action from a fixed safe action set, executes it (rollback / config patch / restart / scale down), verifies the service is healthy again, and logs the full incident.

**Core differentiator:** it acts, not just explains — a `5xx spike detected → root cause: bad env var in latest revision → rollback to last healthy revision → verified healthy → "recovered autonomously"` loop with zero human input.

## 3. Goals (2-day hackathon scope)
- End-to-end demo: trigger a real failure on a real Cloud Run service → agent detects → diagnoses → recovers → verifies → reports.
- Support at least 2 failure types live (crash loop / bad deploy is mandatory; memory leak or error-rate spike is the stretch goal).
- Full audit trail of every incident in Firestore, viewable in a simple dashboard/log view.

## 4. Non-Goals (explicitly out of scope for 2 days)
- No multi-cloud support — Cloud Run + Cloud Logging/Monitoring only.
- No general-purpose anomaly detection ML model — rule-based detection + Gemini diagnosis only.
- No external integrations (CloudWatch, PagerDuty, Slack, MCP) — these are noted as stretch/future scope in §9, not built.
- No production auth/security hardening — hackathon-grade only.
- No dependency on the IIT Mandi GPU cluster — everything runs on Cloud Run/GCP.

## 5. System Architecture
Three modules, connected only through the contracts in §6 — this is what lets all three of you build in parallel from hour 1.

```
[Buggy Service on Cloud Run]  --logs/metrics-->  [A: Watcher]
        ^                                              |
        | rollback / patch+redeploy / restart          v
        |                                    Pub/Sub: failure-events
[C: Orchestrator on Cloud Run] <------------------- topic
        |            |
        v            v
  Firestore      Pub/Sub: recovery-decisions
  (state/log)          |
                        v
                 [B: Diagnosis Agent — Gemini + ADK]
```

- **Person A** owns the target service (deploys the buggy app + failure triggers) and the watcher (detection).
- **Person B** owns the Gemini/ADK diagnosis-and-decision brain (pure function: event in → decision out).
- **Person C** owns Cloud Run orchestration, Pub/Sub plumbing, Firestore state, **executes the actual recovery action via the Cloud Run Admin API**, and the report/dashboard.

## 6. Data Contracts (lock these before writing any code — Hour 1, together)

### 6.1 Failure Event (A → Pub/Sub `failure-events` → C)
```json
{
  "service_id": "string",
  "revision_id": "string",
  "timestamp": "ISO8601",
  "failure_type": "crash_loop | error_rate_spike | memory_leak | bad_deploy | health_check_failure | dependency_failure",
  "log_snippet": "string (last ~50 lines)",
  "metrics": { "error_rate": 0.0, "memory_mb": 0, "restart_count": 0 },
  "last_known_good_revision": "string"
}
```

### 6.2 Recovery Decision (B → C, via Pub/Sub `recovery-decisions` or direct call)
```json
{
  "service_id": "string",
  "diagnosed_cause": "string",
  "confidence": 0.0,
  "chosen_action": "rollback_to_last_good | patch_env_var | increase_memory_limit | restart_instance | scale_down_instance",
  "action_params": { "target_revision": "string", "env_key": "string", "env_value": "string", "memory_mb": 512 },
  "reasoning": "string (1-2 sentences, for the log)"
}
```
Fixed action set only — B must never emit an action outside this list. This is what keeps the agent "safe."

### 6.3 Firestore Schema (owned by C, read by all)
- `services/{service_id}`: status, current_revision, start_time
- `services/{service_id}/incidents/{incident_id}`: failure_event, recovery_decision, action_taken, verification_result, outcome (`recovered` | `failed` | `escalated`)

**Because these three contracts are fixed up front, A, B, and C can build against mocks all of Day 1 and only need each other for integration testing on Day 2.**

## 7. Demo Plan
No GPU or external test infra needed — everything runs on Cloud Run, which is already your stack.

- Deploy a small, deliberately buggy Flask/FastAPI service to Cloud Run — a couple of endpoints, nothing elaborate.
- Build failure triggers directly into the app, gated behind a debug endpoint or env var, so failures are reproducible on demand during the live demo:
  - **Crash loop / bad deploy:** deploy a revision with a broken env var or import error.
  - **Error-rate spike:** a `/break` endpoint that starts throwing 500s on command.
  - **Memory leak:** an endpoint that allocates and holds memory until the container OOMs.
  - **Health check failure:** an endpoint that stalls/hangs past the readiness probe timeout.
- The watcher (Person A) reads from real **Cloud Logging / Cloud Monitoring** — no log-file parsing hacks.
- Recovery is a real **Cloud Run Admin API** call — roll traffic back to the last healthy revision, or patch an env var and redeploy.
- Live demo flow: hit the `/break` (or equivalent) endpoint on stage → watcher detects the spike within seconds → Gemini diagnoses → orchestrator rolls back → judges watch the service go from throwing 500s to healthy, entirely hands-off.

## 8. Work Split — 2 Days, Fully Concurrent

### Person A — Target Service & Watcher
**Deliverable:** a buggy service deployed on Cloud Run with on-demand failure triggers, plus a watcher that detects failures from real Cloud Logging/Monitoring data and publishes events.

**Technical requirements:**
- Small Flask/FastAPI app with 2-3 endpoints, deployed to Cloud Run.
- Debug-gated failure triggers for each failure type in §6.1 (crash loop, error spike, memory leak, health check failure — dependency failure is stretch).
- Structured logging (JSON lines) so Cloud Logging queries are reliable.
- Watcher process (Cloud Function, Cloud Run job, or simple polling script) that queries Cloud Logging/Monitoring, classifies failures against §6.1, and publishes to Pub/Sub topic `failure-events`.
- Deploy a second, deliberately-broken revision on demand (for the bad-deploy scenario) — needed for both testing and the live demo.

**Day 1 (build against the §6.1 contract, no coordination needed):**
- AM: buggy service written and deployed to Cloud Run; all failure triggers working and manually verifiable.
- PM: watcher built, querying Cloud Logging/Monitoring, classifying failures, publishing to Pub/Sub (use the real topic from Person C, or a local mock if C hasn't provisioned it yet).

**Day 2:**
- AM: tighten detection thresholds/timing so failures are caught fast enough for a live demo; prepare the "known bad revision" for the bad-deploy trigger.
- PM: integration with B and C, full failure-injection rehearsal, fix timing/race conditions.

### Person B — Diagnosis & Recovery Agent (Gemini + ADK)
**Deliverable:** a pure decision service — failure event in, recovery decision out, per the §6.2 contract.

**Technical requirements:**
- Google ADK agent setup with Gemini 3.5 Flash as the reasoning model.
- Diagnosis prompt that takes `failure_type`, `log_snippet`, `metrics`, `last_known_good_revision` and returns a structured JSON decision matching §6.2 exactly (use ADK's structured output / function-calling, not free-text parsing).
- Hard-coded, validated action set (5 actions listed in §6.2) — reject/re-prompt if Gemini proposes anything outside it.
- Simple rule fallback (e.g., bad-deploy/crash-loop always rolls back to last known good revision) so the demo never stalls on a bad Gemini response.
- Exposed as a small FastAPI/Cloud Function endpoint OR a Pub/Sub subscriber — whichever Person C's orchestrator expects (decide this at Hour 1).

**Day 1 (build entirely against §6.1/§6.2 mocks — zero dependency on A or C):**
- AM: ADK + Gemini wiring, basic prompt returning valid JSON for a hand-written crash-loop event.
- PM: full action-set coverage, guardrails/validation, test against hand-crafted events for each failure type — no live pipeline needed.

**Day 2:**
- AM: wrap as the actual service C calls (FastAPI endpoint or Pub/Sub subscriber), swap mocks for the real contract.
- PM: integration testing with real events from A, tune prompt against real log snippets, help rehearse demo narration ("here's what Gemini reasoned").

### Person C — Orchestration, Recovery Execution, Infra & Reporting
**Deliverable:** the glue — Cloud Run orchestrator, Pub/Sub plumbing, Firestore state, the actual Cloud Run Admin API recovery call, verification loop, and the report/dashboard.

**Technical requirements:**
- Cloud Run service hosting the orchestrator loop.
- Pub/Sub topics/subscriptions: `failure-events`, `recovery-decisions` (or direct HTTP call to B — decide at Hour 1 and stick to it).
- Firestore schema per §6.3, with write paths from every stage of an incident.
- **Cloud Run Admin API integration** to actually execute the chosen action: traffic rollback to a prior revision, patch env vars and redeploy, or update instance/memory limits.
- Verification logic: after the action, poll the service's health/error-rate for a short window before marking `recovered`.
- A minimal report view — even a Firestore-backed HTML page or a script that prints the incident timeline is enough; polish only if time remains.

**Day 1 (provision infra + build against mocked events from §6.1/§6.2 — no dependency on A/B code):**
- AM: provision Cloud Run, Pub/Sub topics, Firestore; write the orchestrator skeleton that reads a hand-crafted `failure-events` message and writes it to Firestore.
- PM: call B's endpoint (or a stub returning a hard-coded §6.2 payload) and write the decision to Firestore; get the Cloud Run Admin API rollback call working against a manually-deployed test revision.

**Day 2:**
- AM: connect real Pub/Sub feed from A, real decision service from B; implement the verification-and-mark-recovered loop end-to-end.
- PM: build the report view, run full integration + demo rehearsal with A and B, fix cross-component bugs.

## 9. Day-by-Day Sync Points (the only required coordination)
- **Hour 1 (all three, together):** lock §6 contracts — topic names, JSON schemas, and whether B is called via Pub/Sub or direct HTTP. This is the only blocking dependency in the whole plan.
- **End of Day 1 (15 min sync):** each person demos their piece in isolation against the mock/contract, confirms nothing has silently drifted from §6.
- **Day 2 PM:** full integration + demo rehearsal, ideally 2+ dry runs of the live failure-injection demo before presenting.

## 10. Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Gemini returns malformed/unsafe action | Hard validation layer in B rejects anything outside the fixed action set; rule-based fallback |
| Contract drift between A/B/C during parallel work | Lock §6 at Hour 1; treat it as frozen — any change requires a 3-way sync |
| Cloud Logging query latency delays detection on stage | Rehearse timing on Day 2; keep detection thresholds tight (short polling interval) |
| Rollback API call fails live | Have a pre-recorded backup clip of one full recovery loop as fallback |
| Cloud Run cold starts make the demo feel slow | Keep the buggy service warm (min instances = 1) before presenting |

## 11. Stretch Goals / Future Scope (not built in 2 days — mention as roadmap)
Positioned as "DevOps Autopilot" vision beyond the hackathon:
- MCP-based tool connections instead of hardcoded API calls.
- AWS CloudWatch as an alternate/additional monitoring source.
- PagerDuty integration for escalation when the agent can't safely auto-recover.
- Slack integration for real-time incident notifications and human-in-the-loop override.
