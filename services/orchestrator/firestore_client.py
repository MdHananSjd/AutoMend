"""
AutoMend Orchestrator — Firestore Client

Read/write helpers for incident documents in Firestore.
Writes are incremental — status is updated at each stage of the incident lifecycle
so a crash mid-pipeline still leaves a usable partial record.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from google.cloud import firestore

from config import config
from models import (
    IncidentStatus,
    TERMINAL_STATES,
    Incident,
    IncidentTimestamps,
    utcnow_iso,
)

logger = logging.getLogger(__name__)

# Firestore collection path: services/{service_id}/incidents/{incident_id}
SERVICES_COLLECTION = "services"


class FirestoreClient:
    """Firestore client for the AutoMend incident log."""

    def __init__(self) -> None:
        self.db = firestore.Client(
            project=config.GCP_PROJECT_ID,
            region=config.GCP_REGION,
        )

    # ─── Incident document helpers ────────────────────────────────────────

    def _incidents_col(self, service_id: str):
        """Get the incidents subcollection reference for a service."""
        return (
            self.db.collection(SERVICES_COLLECTION)
            .document(service_id)
            .collection("incidents")
        )

    def create_incident(
        self,
        service_id: str,
        incident_id: str,
        failure_event: dict[str, Any],
    ) -> None:
        """Write the initial incident document with status: received."""
        now = utcnow_iso()
        doc_data = {
            "failure_event": failure_event,
            "recovery_decision": None,
            "action_taken": None,
            "verification_result": None,
            "outcome": None,
            "status": IncidentStatus.RECEIVED.value,
            "timestamps": {
                "received": now,
            },
        }
        self._incidents_col(service_id).document(incident_id).set(doc_data)
        logger.info(
            "Created incident %s for service %s (status=received)",
            incident_id,
            service_id,
        )

    def update_incident(
        self,
        service_id: str,
        incident_id: str,
        **fields: Any,
    ) -> None:
        """Partial update of an incident document.

        Usage:
            client.update_incident(sid, iid, status=IncidentStatus.DIAGNOSING)
            client.update_incident(sid, iid, recovery_decision=decision_dict)
        """
        # Convert enum values to strings
        if "status" in fields and isinstance(fields["status"], IncidentStatus):
            fields["status"] = fields["status"].value
        if "outcome" in fields and isinstance(fields["outcome"], IncidentStatus):
            fields["outcome"] = fields["outcome"].value

        # Handle timestamp updates
        if "status" in fields:
            status_val = fields["status"]
            # Remove the status from fields, we'll update timestamps separately
            ts_update = {}
            if status_val in [s.value for s in IncidentStatus]:
                ts_key = status_val
                ts_update[f"timestamps.{ts_key}"] = utcnow_iso()
            fields.pop("status")
            # Build the update dict
            update_dict = {"status": status_val}
            update_dict.update(ts_update)
            update_dict.update(fields)
            self._incidents_col(service_id).document(incident_id).update(update_dict)
        else:
            self._incidents_col(service_id).document(incident_id).update(fields)

        logger.info(
            "Updated incident %s for service %s: %s",
            incident_id,
            service_id,
            list(fields.keys()),
        )

    def get_incident(
        self, service_id: str, incident_id: str
    ) -> Optional[dict[str, Any]]:
        """Read a single incident document."""
        doc = self._incidents_col(service_id).document(incident_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    def get_active_incident(self, service_id: str) -> Optional[dict[str, Any]]:
        """Check for an in-progress incident for this service (idempotency gate).

        Returns the most recent non-terminal incident, or None if all are resolved.
        """
        incidents_ref = self._incidents_col(service_id)
        # Query for non-terminal statuses
        for status in IncidentStatus:
            if status in TERMINAL_STATES:
                continue
            docs = (
                incidents_ref
                .where("status", "==", status.value)
                .order_by("timestamps.received", direction=firestore.Query.DESCENDING)
                .limit(1)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict()
                data["_id"] = doc.id
                return data
        return None

    def list_incidents(
        self, service_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List recent incidents for a service (for the dashboard)."""
        incidents_ref = self._incidents_col(service_id)
        docs = (
            incidents_ref
            .order_by("timestamps.received", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["_id"] = doc.id
            results.append(data)
        return results

    def list_all_incidents(self, limit: int = 100) -> list[dict[str, Any]]:
        """List incidents across all services (for the dashboard).

        Note: This is a collection group query across all incidents subcollections.
        """
        incidents_group = self.db.collection_group("incidents")
        docs = (
            incidents_group
            .order_by("timestamps.received", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["_id"] = doc.id
            data["_service_id"] = doc.reference.parent.parent.id
            results.append(data)
        return results


# Singleton
_firestore_client: Optional[FirestoreClient] = None


def get_firestore_client() -> FirestoreClient:
    """Get or create the Firestore client singleton."""
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = FirestoreClient()
    return _firestore_client
