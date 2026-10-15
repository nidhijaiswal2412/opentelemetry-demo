#!/usr/bin/env python3
"""
main.py - orchestrates config loading, GitHub API calls, normalization, and output.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml

from github_api_client import GitHubClient, GitHubAPIError
from normalize_data import normalize_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rca-prototype")

def load_config(path: Path):
    with open(path, "r") as fh:
        return yaml.safe_load(fh)

def iso_from_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def run():
    base = Path(__file__).parent
    cfg = load_config(base / "config.yaml")
    org = cfg["github"]["organization"]
    repo = cfg["github"]["repository"]
    lookback_m = int(cfg.get("lookback_minutes", 120))
    lookback_dt = datetime.now(timezone.utc) - timedelta(minutes=lookback_m)
    since_iso = iso_from_dt(lookback_dt)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        logger.error("GITHUB_TOKEN not set in environment. Aborting.")
        raise SystemExit(2)

    client = GitHubClient(org, repo, token=token)

    summary = {"calls": []}
    raw = {}

    # Repository
    try:
        rep = client.get_repository()
        summary["calls"].append({"endpoint": f"/repos/{org}/{repo}", "status": rep.get("status")})
        raw["repository"] = rep.get("data")
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": f"/repos/{org}/{repo}", "error": str(e)})
        raw["repository"] = None

    # Commits
    try:
        commits = client.list_commits(since_iso=since_iso)
        summary["calls"].append({"endpoint": f"/commits?since={since_iso}", "count": len(commits)})
        raw["commits"] = commits
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": "/commits", "error": str(e)})
        raw["commits"] = []

    # Workflows
    try:
        workflows = client.list_workflows()
        summary["calls"].append({"endpoint": "/actions/workflows", "count": len(workflows)})
        raw["workflows"] = workflows
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": "/actions/workflows", "error": str(e)})
        raw["workflows"] = []

    # Workflow runs, filtered by lookback client-side
    try:
        runs = client.list_workflow_runs()
        # client returns many runs; filter by created_at >= lookback_dt
        filtered_runs = []
        for r in runs:
            created = r.get("created_at")
            if created:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if dt >= lookback_dt:
                    filtered_runs.append(r)
        summary["calls"].append({"endpoint": "/actions/runs (filtered by lookback)", "count": len(filtered_runs)})
        raw["runs"] = filtered_runs
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": "/actions/runs", "error": str(e)})
        raw["runs"] = []

    # Jobs for runs
    jobs_by_run = {}
    for run in raw.get("runs", []):
        rid = run.get("id")
        try:
            jobs = client.list_jobs_for_run(rid)
            summary["calls"].append({"endpoint": f"/actions/runs/{rid}/jobs", "count": len(jobs)})
            jobs_by_run[str(rid)] = jobs
        except GitHubAPIError as e:
            summary["calls"].append({"endpoint": f"/actions/runs/{rid}/jobs", "error": str(e)})
            jobs_by_run[str(rid)] = []

    raw["jobs_by_run"] = jobs_by_run

    # Deployments
    try:
        deployments = client.list_deployments()
        summary["calls"].append({"endpoint": "/deployments", "count": len(deployments)})
        raw["deployments"] = deployments
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": "/deployments", "error": str(e)})
        raw["deployments"] = []

    # Deployment statuses
    deployment_statuses = {}
    for d in raw.get("deployments", []) or []:
        did = d.get("id")
        try:
            statuses = client.list_deployment_statuses(did)
            summary["calls"].append({"endpoint": f"/deployments/{did}/statuses", "count": len(statuses)})
            deployment_statuses[str(did)] = statuses
        except GitHubAPIError as e:
            summary["calls"].append({"endpoint": f"/deployments/{did}/statuses", "error": str(e)})
            deployment_statuses[str(did)] = []

    raw["deployment_statuses"] = deployment_statuses

    normalized = normalize_all(cfg["service"], cfg["environment"], org, repo, raw)

    outdir = base / "output"
    outdir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    out_path = outdir / f"normalized_{ts}.json"
    with open(out_path, "w") as fh:
        json.dump({"summary": summary, "normalized": normalized}, fh, indent=2)

    print(json.dumps({"summary": summary, "normalized": normalized}, indent=2))
    logger.info("Wrote normalized output: %s", out_path)
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
