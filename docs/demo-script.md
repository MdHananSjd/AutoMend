# AutoMend — Demo Script

This is the walkthrough used for both the recorded submission video and any live judge demo. It's written to be followed step by step, with rough timing, so it's reproducible under pressure.

## Pre-demo checklist (do this before recording/presenting)
- [ ] Target service deployed and healthy — confirm its normal endpoint responds correctly.
- [ ] A second, deliberately broken revision is built and ready to deploy on demand (for the bad-deploy scenario), but **not yet deployed**.
- [ ] Watcher, Diagnosis Agent, and Orchestrator all deployed and confirmed reachable.
- [ ] Dashboard loaded in a browser tab, empty/idle state confirmed.
- [ ] Cloud Logging tab open in a second browser tab (optional, but useful to show the raw signal the Watcher is reading).
- [ ] Min instances set to 1 on the target service and orchestrator, to avoid a cold-start delay during the live moment.
- [ ] Do at least two full dry runs of this script before recording/presenting for real.

## Scenario 1 — Error-rate spike → rollback (primary/mandatory demo)

**Narration beat:** "Here's AutoMend watching a live service. I'm going to break it, and I'm not going to touch anything after that."

1. **(0:00)** Show the dashboard in its idle state and the target service responding normally.
2. **(0:10)** Hit the target service's `/break` endpoint (or run the provided trigger script) to force a sustained 500-error loop.
3. **(0:15–0:30)** Narrate what's happening while it plays out: "The Watcher is polling Cloud Logging right now — within a few seconds it'll see the error rate cross the threshold and publish a Failure Event."
4. **(~0:30–0:45)** Point out the new incident appearing on the dashboard with status `received`, then `diagnosing`.
5. **(~0:45–1:00)** Show the Recovery Decision once it lands — read out the `diagnosed_cause` and `reasoning` fields live, since this is the most "agentic" moment of the demo.
6. **(~1:00–1:15)** Show the incident move to `action_taken` (`rollback_to_last_good`), and the target service's traffic actually shift in the Cloud Run console.
7. **(~1:15–1:30)** Hit the target service's normal endpoint again to show it responding correctly.
8. **(~1:30)** Dashboard shows `recovered`. Close the loop verbally: "No human touched this. Detection to recovery took under [X] seconds."

## Scenario 2 — Bad deploy → rollback (stretch, if time allows)

1. Deploy the pre-built broken revision to the target service.
2. Narrate: this simulates someone shipping a bad env var/config change.
3. Same flow as Scenario 1 — Watcher detects the crash loop, Diagnosis Agent identifies `bad_deploy` as the cause, Orchestrator rolls back.
4. Useful to show back-to-back with Scenario 1 to demonstrate the same recovery path handles two different root causes correctly.

## Scenario 3 — Memory leak (stretch, only if Scenarios 1–2 are solid and time remains)

1. Hit the memory-allocation endpoint until the container is OOM-killed.
2. Narrate that this is a different failure signature (OOM-kill event / restart count, not an error-rate spike) and a different recovery action (`increase_memory_limit`), to show the system isn't hardcoded to one type of fix.

## What to say if something goes wrong live
Have this ready rather than improvising:
- If detection is slow: "Detection latency depends on the Cloud Logging polling interval — in production this would be tuned much tighter than our demo config."
- If the Diagnosis Agent's decision looks off: read out the `reasoning` field anyway — it's still informative even if the confidence is lower than ideal, and shows the guardrail/fallback logic is doing its job rather than acting blindly.
- If the live demo truly breaks: cut to the pre-recorded backup clip of one full successful recovery loop (see checklist below) rather than debugging on stage.

## Recording checklist for the submission video
- [ ] Record one full clean run of Scenario 1 as a backup clip, even if presenting live — insurance against a live failure.
- [ ] Keep the final video within whatever length limit the hackathon submission requires (confirm this against the official rules before finalizing).
- [ ] Include a brief intro (problem statement, ~15–20 seconds) before diving into the live demo, per the framing in the README.
- [ ] Show the Firestore incident record and/or dashboard as evidence, not just narration — judges should see the audit trail, not just hear about it.