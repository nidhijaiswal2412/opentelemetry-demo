"""
normalize_data.py

Convert raw GitHub API responses into the RCA normalized schema.

This stricter version keeps workflow execution data separate from deployment data,
preserves workflow status and conclusion as separate fields, and only populates
top-level deployment fields when explicit deployment evidence exists.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

BASE_SCHEMA = {
    "service": None,
    "environment": None,
    "source": "github-actions",
    "repository": None,
    "pipeline": None,
    "deploymentId": None,
    "buildId": None,
    "commitSha": None,
    "branch": None,
    "version": None,
    "image": None,
    "status": None,
    "deploymentStart": None,
    "deploymentEnd": None,
    "author": None,
    "deploymentUrl": None,
    "evidence": []
}


def _iso_keep(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s
    except Exception:
        return s


def normalize_all(service: str, environment: str, org: str, repo: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(BASE_SCHEMA)
    out["service"] = service
    out["environment"] = environment
    out["repository"] = f"{org}/{repo}"
    out["evidence"] = []

    runs = raw.get("runs", []) or []
    deployments = raw.get("deployments", []) or []
    jobs_by_run = raw.get("jobs_by_run", {}) or {}
    commits = raw.get("commits", []) or []

    def author_from_commit(sha: Optional[str]) -> Optional[str]:
        if not sha:
            return None
        for c in commits:
            if c.get("sha") == sha:
                return c.get("commit", {}).get("author", {}).get("name") or (c.get("author") or {}).get("login")
        return None

    # --- Workflow run evidence (kept separate from deployment evidence) ---
    for run in runs:
        run_id = run.get("id")
        workflow_id = run.get("workflow_id")
        # Build an evidence item describing the workflow run. Do NOT map run timestamps
        # to deploymentStart/deploymentEnd unless linked to a deployment record.
        item: Dict[str, Any] = {
            "source": "github-actions",
            "workflow_name": run.get("name"),
            "workflow_id": workflow_id,
            "run_id": run_id,
            # keep buildId inside evidence to map run -> build
            "buildId": run_id,
            "commitSha": run.get("head_sha"),
            "branch": run.get("head_branch"),
            "run_status": run.get("status"),
            "run_conclusion": run.get("conclusion"),
            # do not populate deploymentStart/deploymentEnd for workflow runs
            "deploymentStart": None,
            "deploymentEnd": None,
            "author": (run.get("actor") or {}).get("login") or author_from_commit(run.get("head_sha")),
            "url": run.get("html_url"),
            "evidence": [],
            # Which API record supports this evidence
            "supported_by": [
                {"api": "actions/runs", "record_id": run_id, "fields": [
                    "id", "workflow_id", "name", "head_sha", "head_branch", "status", "conclusion", "created_at", "updated_at", "html_url"
                ]}
            ]
        }

        # Attach job-level evidence (kept nested under this run evidence).
        run_jobs = jobs_by_run.get(str(run_id)) or jobs_by_run.get(run_id) or []
        for j in run_jobs:
            je = {
                "job_name": j.get("name"),
                "job_id": j.get("id"),
                "job_status": j.get("status"),
                "job_conclusion": j.get("conclusion"),
                "started_at": _iso_keep(j.get("started_at")),
                "completed_at": _iso_keep(j.get("completed_at")),
                "job_url": j.get("html_url"),
                "supported_by": [{"api": f"actions/runs/{run_id}/jobs", "record_id": j.get("id"), "fields": ["id", "name", "status", "conclusion", "started_at", "completed_at", "html_url"]}]
            }
            item["evidence"].append(je)

        out["evidence"].append(item)

    # --- Deployment evidence (explicit GitHub Deployments API) ---
    for d in deployments:
        dep_id = d.get("id")
        dep_item: Dict[str, Any] = {
            "source": "github-deployments",
            "deploymentId": dep_id,
            "commitSha": d.get("sha"),
            "ref": d.get("ref"),
            "environment": d.get("environment"),
            "version": d.get("task" ) or None,
            "image": None,  # only populated when explicit image metadata is present
            "deploymentStatus": None,
            "deploymentStart": _iso_keep(d.get("created_at")),
            "deploymentEnd": None,
            "author": (d.get("creator") or {}).get("login"),
            "deploymentUrl": d.get("url"),
            "evidence": [],
            "supported_by": [{"api": "deployments", "record_id": dep_id, "fields": ["id", "sha", "ref", "task", "creator", "created_at", "url"]}]
        }

        statuses = raw.get("deployment_statuses", {}).get(str(dep_id)) or raw.get("deployment_statuses", {}).get(dep_id) or []
        if statuses:
            latest = sorted(statuses, key=lambda s: s.get("created_at") or "", reverse=True)[0]
            dep_item["deploymentStatus"] = latest.get("state")
            dep_item["deploymentEnd"] = _iso_keep(latest.get("updated_at") or latest.get("created_at"))
            dep_item["evidence"].append({"deployment_status_record": latest, "supported_by": [{"api": f"deployments/{dep_id}/statuses", "record_id": latest.get("id"), "fields": list(latest.keys())}]})

        # Try to extract version or image from deployment payloads/description if present
        payload = d.get("payload") or {}
        if isinstance(payload, dict):
            # Common fields might include "version", "image", "tag"
            dep_item["version"] = payload.get("version") or dep_item["version"]
            dep_item["image"] = payload.get("image") or dep_item["image"]
            if payload:
                dep_item["supported_by"].append({"api": f"deployments (payload)", "record_id": dep_id, "fields": list(payload.keys())})

        out["evidence"].append(dep_item)

    # --- Populate top-level deployment summary only if explicit deployment evidence exists ---
    deployment_evidence = [e for e in out.get("evidence", []) if e.get("source") == "github-deployments"]
    if deployment_evidence:
        # Choose the most recent deployment by start time
        pick = sorted(deployment_evidence, key=lambda x: x.get("deploymentStart") or "", reverse=True)[0]
        out["pipeline"] = None
        out["deploymentId"] = pick.get("deploymentId")
        out["buildId"] = None  # only set if deployment links to a run/build explicitly
        out["commitSha"] = pick.get("commitSha")
        out["branch"] = pick.get("ref")
        out["status"] = pick.get("deploymentStatus")
        out["deploymentStart"] = pick.get("deploymentStart")
        out["deploymentEnd"] = pick.get("deploymentEnd")
        out["author"] = pick.get("author")
        out["deploymentUrl"] = pick.get("deploymentUrl")
        out["version"] = pick.get("version")
        out["image"] = pick.get("image")
    else:
        # No explicit deployments found: keep deployment/top-level fields null.
        out["pipeline"] = None
        out["deploymentId"] = None
        out["buildId"] = None
        out["commitSha"] = None
        out["branch"] = None
        out["status"] = None
        out["deploymentStart"] = None
        out["deploymentEnd"] = None
        out["author"] = None
        out["deploymentUrl"] = None
        out["version"] = None
        out["image"] = None

    return out
