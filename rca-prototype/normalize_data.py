"""
normalize_data.py

Convert raw GitHub API responses into the RCA normalized schema.
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
    # Validate briefly; if invalid, return original
    try:
        # Accept strings like "YYYY-MM-DDTHH:MM:SSZ" or with offset
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

    # Normalize workflow runs into evidence items
    for run in runs:
        run_id = run.get("id")
        item: Dict[str, Any] = {
            "service": service,
            "environment": environment,
            "source": "github-actions",
            "repository": f"{org}/{repo}",
            "pipeline": run.get("name") or run.get("path") or run.get("workflow_id"),
            "deploymentId": None,
            "buildId": run_id,
            "commitSha": run.get("head_sha"),
            "branch": run.get("head_branch"),
            "version": None,
            "image": None,
            "status": run.get("status") or run.get("conclusion"),
            "deploymentStart": _iso_keep(run.get("run_started_at") or run.get("created_at")),
            "deploymentEnd": _iso_keep(run.get("updated_at") or run.get("completed_at")),
            "author": (run.get("actor") or {}).get("login") or author_from_commit(run.get("head_sha")),
            "deploymentUrl": run.get("html_url"),
            "evidence": []
        }

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
            }
            item["evidence"].append(je)

        out["evidence"].append(item)

    # Normalize explicit deployments
    for d in deployments:
        dep_id = d.get("id")
        dep_item: Dict[str, Any] = {
            "service": service,
            "environment": environment,
            "source": "github-deployments",
            "repository": f"{org}/{repo}",
            "pipeline": None,
            "deploymentId": dep_id,
            "buildId": None,
            "commitSha": d.get("sha"),
            "branch": d.get("ref"),
            "version": None,
            "image": None,
            "status": None,
            "deploymentStart": _iso_keep(d.get("created_at")),
            "deploymentEnd": None,
            "author": (d.get("creator") or {}).get("login"),
            "deploymentUrl": d.get("url"),
            "evidence": []
        }

        statuses = raw.get("deployment_statuses", {}).get(str(dep_id)) or raw.get("deployment_statuses", {}).get(dep_id) or []
        if statuses:
            # choose most recent status
            latest = sorted(statuses, key=lambda s: s.get("created_at") or "", reverse=True)[0]
            dep_item["status"] = latest.get("state")
            dep_item["deploymentEnd"] = _iso_keep(latest.get("updated_at") or latest.get("created_at"))
            dep_item["evidence"].append({"status_record": latest})

        out["evidence"].append(dep_item)

    # Populate top-level fields from most recent evidence (prefer deployments)
    if out["evidence"]:
        deps = [e for e in out["evidence"] if e.get("source") == "github-deployments"]
        pick = None
        if deps:
            pick = sorted(deps, key=lambda x: x.get("deploymentStart") or "", reverse=True)[0]
        else:
            pick = sorted(out["evidence"], key=lambda x: x.get("deploymentStart") or x.get("deploymentEnd") or "", reverse=True)[0]

        out["pipeline"] = pick.get("pipeline")
        out["deploymentId"] = pick.get("deploymentId")
        out["buildId"] = pick.get("buildId")
        out["commitSha"] = pick.get("commitSha")
        out["branch"] = pick.get("branch")
        out["status"] = pick.get("status")
        out["deploymentStart"] = pick.get("deploymentStart")
        out["deploymentEnd"] = pick.get("deploymentEnd")
        out["author"] = pick.get("author")
        out["deploymentUrl"] = pick.get("deploymentUrl")

    return out
