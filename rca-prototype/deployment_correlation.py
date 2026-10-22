"""
Deployment-correlation evaluation for the RCA prototype.

This helper is intentionally strict:
- requires explicit service match to checkout
- requires exact environment equality to "development"
- never treats deployment request created_at as rollout proof
- requires defensible deployment-status timestamps and state semantics
- excludes post-onset successful rollout from probable causes
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _explicit_service(deployment: Dict[str, Any]) -> Optional[str]:
    if not isinstance(deployment, dict):
        return None

    for key in ("service", "service_name", "application", "app"):
        value = deployment.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()

    payload = deployment.get("payload")
    if isinstance(payload, dict):
        for key in ("service", "service_name", "application", "app"):
            value = payload.get(key)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
    return None


def _explicit_environment(deployment: Dict[str, Any]) -> Optional[str]:
    if not isinstance(deployment, dict):
        return None

    for key in ("environment", "environment_name"):
        value = deployment.get(key)
        if value is not None and str(value).strip() != "":
            return str(value)

    payload = deployment.get("payload")
    if isinstance(payload, dict):
        for key in ("environment", "environment_name"):
            value = payload.get(key)
            if value is not None and str(value).strip() != "":
                return str(value)
    return None


def _select_status_timestamp(status: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[str]]:
    if not isinstance(status, dict):
        return None, None

    created = _parse_iso(status.get("created_at"))
    updated = _parse_iso(status.get("updated_at"))

    if created is not None:
        return created, "created_at"
    if updated is not None:
        return updated, "updated_at"
    return None, None


def _deployment_status_records(
    deployment_id: Any,
    deployment_statuses: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    if deployment_id is None:
        return []
    status_list = deployment_statuses.get(str(deployment_id))
    if status_list is None:
        status_list = deployment_statuses.get(deployment_id)
    if status_list is None:
        return []
    return status_list if isinstance(status_list, list) else []


def _build_status_candidates(statuses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for status in statuses or []:
        if not isinstance(status, dict):
            continue
        state = str(status.get("state") or "").strip().lower()
        if not state:
            continue
        ts, source = _select_status_timestamp(status)
        if ts is None:
            continue
        candidates.append({
            "state": state,
            "timestamp": ts,
            "timestamp_source": source,
            "record": status,
        })
    return sorted(candidates, key=lambda item: item["timestamp"])


def correlate_deployment_evidence(
    deployments: List[Dict[str, Any]],
    deployment_statuses: Dict[str, List[Dict[str, Any]]],
    incident_service: str,
    incident_onset: str,
    environment: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return probable causes and recovery context using only strict deployment-status evidence."""
    probable_causes: List[Dict[str, Any]] = []
    recovery_context: List[Dict[str, Any]] = []

    if incident_service != "checkout":
        return probable_causes, recovery_context
    if environment != "development":
        return probable_causes, recovery_context

    onset_dt = _parse_iso(incident_onset)
    if onset_dt is None:
        return probable_causes, recovery_context

    for deployment in deployments or []:
        if not isinstance(deployment, dict):
            continue

        dep_id = deployment.get("id")
        service_name = _explicit_service(deployment)
        env_name = _explicit_environment(deployment)

        if service_name is None:
            recovery_context.append({
                "service": None,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": None,
                "rolloutAt": None,
                "reason": "Missing explicit service metadata; deployment cannot be matched to checkout.",
                "source": "github-deployments",
            })
            continue

        if str(service_name) != "checkout":
            recovery_context.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": None,
                "rolloutAt": None,
                "reason": "Deployment service is not checkout; explicit service match required.",
                "source": "github-deployments",
            })
            continue

        if env_name != "development":
            recovery_context.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": None,
                "rolloutAt": None,
                "reason": "Deployment environment is not exactly development; exact match required.",
                "source": "github-deployments",
            })
            continue

        statuses = _deployment_status_records(dep_id, deployment_statuses)
        if not statuses:
            recovery_context.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": None,
                "rolloutAt": None,
                "reason": "No deployment-status evidence available; created_at alone is not rollout proof.",
                "source": "github-deployments",
            })
            continue

        status_candidates = _build_status_candidates(statuses)
        if not status_candidates:
            recovery_context.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": None,
                "rolloutAt": None,
                "reason": "Deployment-status timestamps are missing or invalid; rollout timing cannot be established reliably.",
                "source": "github-deployments",
            })
            continue

        success_before = [
            item for item in status_candidates
            if item["state"] == "success" and item["timestamp"] <= onset_dt
        ]
        success_after = [
            item for item in status_candidates
            if item["state"] == "success" and item["timestamp"] > onset_dt
        ]

        if success_before:
            selected = min(success_before, key=lambda item: item["timestamp"])
            probable_causes.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": selected["state"],
                "rolloutAt": selected["record"].get("created_at") or selected["record"].get("updated_at"),
                "timestampSource": selected["timestamp_source"],
                "record": selected["record"],
                "reason": "Verified successful deployment rollout occurred at or before incident onset and passed explicit service/environment checks.",
                "source": "github-deployments",
            })
            continue

        if success_after:
            recovery_context.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": "success",
                "rolloutAt": success_after[0]["record"].get("created_at") or success_after[0]["record"].get("updated_at"),
                "timestampSource": success_after[0]["timestamp_source"],
                "reason": "Successful rollout occurred after incident onset; excluded from probable causes.",
                "source": "github-deployments",
            })
            continue

        if any(item["state"] in {"error", "failure", "inactive"} for item in status_candidates):
            recovery_context.append({
                "service": service_name,
                "environment": env_name,
                "deploymentId": dep_id,
                "deploymentStatus": "error" if any(item["state"] == "error" for item in status_candidates) else "failure",
                "rolloutAt": None,
                "reason": "Deployment-status history shows failure/error/inactive states and no defensible successful rollout before incident onset.",
                "source": "github-deployments",
            })
            continue

        recovery_context.append({
            "service": service_name,
            "environment": env_name,
            "deploymentId": dep_id,
            "deploymentStatus": None,
            "rolloutAt": None,
            "reason": "No defensible successful rollout before incident onset could be established from deployment-status evidence.",
            "source": "github-deployments",
        })

    return probable_causes, recovery_context
