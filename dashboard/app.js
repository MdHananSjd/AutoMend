/**
 * AutoMend Dashboard — Firebase Firestore Real-Time Listener
 *
 * Reads incidents from Firestore in real time via onSnapshot.
 * Shows live status changes as the orchestrator progresses through stages.
 *
 * Configuration: update the firebaseConfig below with your project's values.
 */

// ─── Firebase Configuration ──────────────────────────────────────────────
// ⚠ Replace these values with your actual Firebase project config.
// Find them in: Firebase Console → Project Settings → General → Your apps → Firebase SDK snippet

// ─── Firebase Configuration ──────────────────────────────────────────────
// These values are project identifiers, not secrets. Firebase web API keys
// are public by design — security is enforced by Firestore rules, not the key.
const firebaseConfig = {
    apiKey: "AIzaSyARIULZpu714_Qw0IC72yPIz0Kg3eHEIbE",
    authDomain: "automend-hackathon.firebaseapp.com",
    projectId: "automend-hackathon",
    storageBucket: "automend-hackathon.appspot.com",
    messagingSenderId: "247530183292",
    appId: "1:247530183292:web:f98560c12c52931ed747f9",
};

// ─── Initialize Firebase ─────────────────────────────────────────────────

firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();

// ─── State ───────────────────────────────────────────────────────────────

let incidents = [];
let unsubscribe = null;

// ─── DOM References ──────────────────────────────────────────────────────

const incidentsList = document.getElementById("incidents-list");
const emptyState = document.getElementById("empty-state");
const connectionStatus = document.getElementById("connection-status");
const statTotal = document.getElementById("stat-total");
const statRecovered = document.getElementById("stat-recovered");
const statInProgress = document.getElementById("stat-in-progress");
const statFailed = document.getElementById("stat-failed");

// ─── Helpers ─────────────────────────────────────────────────────────────

const TERMINAL_STATES = new Set(["recovered", "failed", "escalated"]);
const IN_PROGRESS_STATES = new Set(["received", "diagnosing", "action_taken", "verifying"]);
const FAILED_STATES = new Set(["failed", "escalated"]);

const STATUS_LABELS = {
    received: "Received",
    diagnosing: "Diagnosing",
    action_taken: "Action Taken",
    verifying: "Verifying",
    recovered: "Recovered",
    failed: "Failed",
    escalated: "Escalated",
};

const FAILURE_TYPE_LABELS = {
    crash_loop: "🔄 Crash Loop",
    error_rate_spike: "📈 Error Rate Spike",
    memory_leak: "💾 Memory Leak",
    bad_deploy: "🚀 Bad Deploy",
    health_check_failure: "❤️‍🩹 Health Check Failure",
    dependency_failure: "🔗 Dependency Failure",
};

const TIMELINE_STEPS = ["received", "diagnosing", "action_taken", "verifying", "recovered"];

function formatTime(isoString) {
    if (!isoString) return "—";
    const date = new Date(isoString);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

// ─── Render Functions ────────────────────────────────────────────────────

function updateStats() {
    const total = incidents.length;
    const recovered = incidents.filter((i) => i.status === "recovered").length;
    const inProgress = incidents.filter((i) => IN_PROGRESS_STATES.has(i.status)).length;
    const failed = incidents.filter((i) => FAILED_STATES.has(i.status)).length;

    statTotal.textContent = total;
    statRecovered.textContent = recovered;
    statInProgress.textContent = inProgress;
    statFailed.textContent = failed;
}

function renderTimeline(incident) {
    const currentStatus = incident.status;
    const isTerminal = TERMINAL_STATES.has(currentStatus);

    let steps = [...TIMELINE_STEPS];
    if (isTerminal && !steps.includes(currentStatus)) {
        steps.push(currentStatus);
    }

    const currentIndex = steps.indexOf(currentStatus);

    return steps
        .map((step, index) => {
            let stepClass = "";
            if (index < currentIndex) stepClass = "completed";
            else if (index === currentIndex) stepClass = "active";
            else if (isTerminal && currentStatus !== "recovered") stepClass = "failed";

            return `<span class="timeline-step ${stepClass}">
                <span class="step-dot"></span>
                ${STATUS_LABELS[step] || step}
            </span>`;
        })
        .join('<span class="timeline-arrow">→</span>');
}

function renderIncident(incident) {
    const serviceId = incident._service_id || incident.failure_event?.service_id || "unknown";
    const failureType = incident.failure_event?.failure_type || "unknown";
    const chosenAction = incident.recovery_decision?.chosen_action || "—";
    const reasoning = incident.recovery_decision?.reasoning || "";
    const diagnosedCause = incident.recovery_decision?.diagnosed_cause || "";
    const confidence = incident.recovery_decision?.confidence;
    const timestamp = incident.timestamps?.received || "";
    const incidentId = incident._id || "";

    const card = document.createElement("div");
    card.className = "incident-card";
    card.setAttribute("data-incident-id", incidentId);

    card.innerHTML = `
        <div class="incident-header">
            <div class="incident-title">
                <span class="service-id">${serviceId} · ${formatDate(timestamp)} ${formatTime(timestamp)}</span>
                <span class="failure-type">${FAILURE_TYPE_LABELS[failureType] || failureType}</span>
            </div>
            <span class="status-badge ${incident.status}">${STATUS_LABELS[incident.status] || incident.status}</span>
        </div>
        <div class="incident-details">
            <div class="detail-item">
                <span class="detail-label">Action</span>
                <span class="detail-value">${chosenAction.replace(/_/g, " ")}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Diagnosed Cause</span>
                <span class="detail-value">${diagnosedCause || "—"}</span>
            </div>
            ${confidence !== undefined && confidence !== null ? `
            <div class="detail-item">
                <span class="detail-label">Confidence</span>
                <span class="detail-value">${(confidence * 100).toFixed(0)}%</span>
            </div>` : ""}
            <div class="detail-item">
                <span class="detail-label">Incident ID</span>
                <span class="detail-value">${incidentId.substring(0, 12)}…</span>
            </div>
        </div>
        <div class="incident-timeline">
            ${renderTimeline(incident)}
        </div>
        ${reasoning ? `
        <div class="reasoning">
            <div class="label">Agent Reasoning</div>
            <div class="text">"${reasoning}"</div>
        </div>` : ""}
    `;

    return card;
}

function renderIncidents() {
    // Clear existing cards (but keep the empty state element)
    const existingCards = incidentsList.querySelectorAll(".incident-card");
    existingCards.forEach((card) => card.remove());

    if (incidents.length === 0) {
        emptyState.style.display = "block";
        return;
    }

    emptyState.style.display = "none";

    incidents.forEach((incident) => {
        const card = renderIncident(incident);
        incidentsList.appendChild(card);
    });

    updateStats();
}

// ─── Firestore Real-Time Listener ────────────────────────────────────────

function startListening() {
    // Listen to all incidents across all services using collectionGroup
    // Fall back to a single service collection if collectionGroup isn't set up
    let query;

    try {
        // collectionGroup query — requires a Firestore index on incidents
        query = db.collectionGroup("incidents")
            .orderBy("timestamps.received", "desc")
            .limit(50);
    } catch (e) {
        // Fallback: listen to a specific service's incidents
        console.warn("collectionGroup failed, falling back to single service:", e);
        query = db.collection("services")
            .doc("automend-target")
            .collection("incidents")
            .orderBy("timestamps.received", "desc")
            .limit(50);
    }

    unsubscribe = query.onSnapshot(
        (snapshot) => {
            incidents = [];
            snapshot.forEach((doc) => {
                const data = doc.data();
                data._id = doc.id;
                // Try to extract service_id from the document path
                // Path: services/{serviceId}/incidents/{incidentId}
                const parentPath = doc.ref.parent.parent;
                if (parentPath) {
                    data._service_id = parentPath.id;
                }
                incidents.push(data);
            });

            renderIncidents();
            setConnectionStatus("connected");
        },
        (error) => {
            console.error("Firestore listener error:", error);
            setConnectionStatus("error");

            // If collectionGroup fails, try the fallback
            if (error.code === "failed-precondition") {
                console.log("Retrying with single-service fallback...");
                startFallbackListening();
            }
        }
    );
}

function startFallbackListening() {
    if (unsubscribe) unsubscribe();

    const query = db.collection("services")
        .doc("automend-target")
        .collection("incidents")
        .orderBy("timestamps.received", "desc")
        .limit(50);

    unsubscribe = query.onSnapshot(
        (snapshot) => {
            incidents = [];
            snapshot.forEach((doc) => {
                const data = doc.data();
                data._id = doc.id;
                data._service_id = "automend-target";
                incidents.push(data);
            });
            renderIncidents();
            setConnectionStatus("connected");
        },
        (error) => {
            console.error("Fallback listener error:", error);
            setConnectionStatus("error");
        }
    );
}

function setConnectionStatus(status) {
    connectionStatus.className = "status-indicator " + status;
    const label = connectionStatus.querySelector(".label");
    switch (status) {
        case "connected":
            label.textContent = "Live";
            break;
        case "error":
            label.textContent = "Error";
            break;
        default:
            label.textContent = "Connecting...";
    }
}

// ─── Initialize ──────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    console.log("AutoMend Dashboard initializing...");
    startListening();
});

// Cleanup on page unload
window.addEventListener("beforeunload", () => {
    if (unsubscribe) unsubscribe();
});
