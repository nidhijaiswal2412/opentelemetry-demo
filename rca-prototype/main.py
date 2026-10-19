#!/usr/bin/env python3
"""
main.py - orchestrates config loading, GitHub API calls, normalization, and output.
"""

import json
import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from github_api_client import GitHubAPIError, GitHubClient
from normalize_data import normalize_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rca-prototype")


def load_config(path: Path):
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def parse_iso(value):
    if value is None:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def iso_from_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_incident(cfg):
    source = cfg.get("incident_source", "env")
    if source == "env":
        raw = os.getenv(cfg.get("incident_env_var", "INCIDENT_PAYLOAD"))
        if raw:
            return json.loads(raw)
    elif source == "file":
        path = Path(cfg.get("incident_file", "rca-prototype/incident.json"))
        if path.exists():
            return json.loads(path.read_text())
    return None


def load_dependency_map(cfg):
    dep_path = Path(cfg.get("dependency_file", "rca-prototype/service_dependencies.yaml"))
    if not dep_path.exists():
        return {}
    data = yaml.safe_load(dep_path.read_text()) or {}
    return data.get("services", {})


def filter_by_window(items, window_start, window_end):
    result = []
    for item in items:
        created = item.get("created_at") or item.get("created_time") or item.get("updated_at")
        if not created:
            continue
        try:
            dt = parse_iso(created)
        except Exception:
            continue
        if window_start <= dt <= window_end:
            result.append(item)
    return result


def infer_service_from_paths(paths, known_services):
    if not paths:
        return None
    for path in paths:
        if not isinstance(path, str):
            continue
        clean = path.strip().lstrip("./")
        for service in known_services:
            if clean == service or clean.startswith(f"src/{service}/") or clean.startswith(f"{service}/"):
                return service
    return None


def collect_related_services(service_name, graph, depth=2):
    def bfs(initial_service, relation_key):
        q = deque([(initial_service, 0)])
        seen = {initial_service}
        found = set()
        while q:
            current, level = q.popleft()
            if level >= depth:
                continue
            for neighbor in graph.get(current, {}).get(relation_key, []):
                if neighbor not in seen:
                    seen.add(neighbor)
                    found.add(neighbor)
                    q.append((neighbor, level + 1))
        return found

    upstream = bfs(service_name, "upstream")
    downstream = bfs(service_name, "downstream")
    return {"incident": service_name, "upstream": sorted(upstream), "downstream": sorted(downstream)}


def run():
    base = Path(__file__).parent
    cfg = load_config(base / "config.yaml")
    org = cfg["github"]["organization"]
    repo = cfg["github"]["repository"]
    dependency_graph = load_dependency_map(cfg)
    dependency_depth = int(cfg.get("dependency_depth", 2))

    incident = load_incident(cfg)
    incident_service = cfg.get("service", "opentelemetry-demo")
    if incident and isinstance(incident, dict):
        incident_service = incident.get("service") or incident_service
        started_at = parse_iso(incident.get("started_at"))
        if started_at is None:
            logger.warning("Incident payload missing started_at; using current time for window.")
            started_at = datetime.now(timezone.utc)
    else:
        started_at = datetime.now(timezone.utc)

    window_start = started_at - timedelta(hours=int(cfg.get("lookback_hours", 3)))
    window_end = started_at + timedelta(minutes=int(cfg.get("lookforward_minutes", 20)))

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        logger.error("GITHUB_TOKEN not set in environment. Aborting.")
        raise SystemExit(2)

    client = GitHubClient(org, repo, token=token)

    summary = {"calls": [], "window_start": iso_from_dt(window_start), "window_end": iso_from_dt(window_end), "incident": incident}
    raw = {}

    # Repository metadata
    try:
        rep = client.get_repository()
        summary["calls"].append({"endpoint": f"/repos/{org}/{repo}", "status": rep.get("status")})
        raw["repository"] = rep.get("data")
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": f"/repos/{org}/{repo}", "error": str(e)})
        raw["repository"] = None

    # Commits in the window
    try:
        commits = client.list_commits(since_iso=iso_from_dt(window_start))
        summary["calls"].append({"endpoint": f"/commits?since={iso_from_dt(window_start)}", "count": len(commits)})
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

    # Workflow runs in the incident window
    try:
        runs = client.list_workflow_runs()
        filtered_runs = []
        for run in runs:
            created = run.get("created_at")
            if not created:
                continue
            try:
                dt = parse_iso(created)
            except Exception:
                continue
            if window_start <= dt <= window_end:
                filtered_runs.append(run)
        summary["calls"].append({"endpoint": "/actions/runs (filtered by incident window)", "count": len(filtered_runs)})
        raw["runs"] = filtered_runs
    except GitHubAPIError as e:
        summary["calls"].append({"endpoint": "/actions/runs", "error": str(e)})
        raw["runs"] = []

    # Jobs for runs in the window
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

    # Deployments in the window
    try:
        deployments = client.list_deployments()
        filtered_deployments = []
        for deployment in deployments:
            created = deployment.get("created_at")
            if not created:
                continue
            try:
                dt = parse_iso(created)
            except Exception:
                continue
            if window_start <= dt <= window_end:
                filtered_deployments.append(deployment)
        summary["calls"].append({"endpoint": "/deployments (filtered by incident window)", "count": len(filtered_deployments)})
        raw["deployments"] = filtered_deployments
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

    # Service dependency expansion for the incident service
    if dependency_graph:
        related = collect_related_services(incident_service, dependency_graph, depth=dependency_depth)
    else:
        related = {"incident": incident_service, "upstream": [], "downstream": []}

    # Map run evidence to service(s) conservatively using commit file paths
    affected_services = []
    for service_name in [incident_service] + related["upstream"] + related["downstream"]:
        service_evidence = []
        for ev in normalized.get("evidence", []):
            if ev.get("source") == "github-actions":
                sha = ev.get("commitSha")
                if sha:
                    try:
                        commit = client.get_commit(sha)
                    except GitHubAPIError:
                        continue
                    files = []
                    if isinstance(commit, dict):
                        files = commit.get("files", []) or []
                    filenames = [f.get("filename") for f in files if isinstance(f, dict)]
                    inferred = infer_service_from_paths(filenames, set(dependency_graph.keys()))
                    if inferred and inferred == service_name:
                        service_evidence.append(ev)
                elif service_name == incident_service:
                    # if no sha, still keep incident-service evidence as direct incident service
                    service_evidence.append(ev)

        # Include deployment evidence for the service if the normalized deployment evidence matches same commit or same ref?
        # We will not fabricate a matching deployment for arbitrary services without explicit deployment data.
        affected_services.append({
            "service": service_name,
            "role": "incident" if service_name == incident_service else (
                "upstream" if service_name in related["upstream"] else "downstream"
            ),
            "evidence": service_evidence,
            "notes": "GitHub Actions evidence filtered to the incident window and service dependency graph. Deployment evidence is only included when GitHub Deployments API returned a deployment record."
        })

    outdir = base / "output"
    outdir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    out_path = outdir / f"normalized_{ts}.json"
    payload = {
        "summary": summary,
        "normalized": normalized,
        "affected_services": affected_services,
        "related_services": related,
        "incident_service": incident_service,
        "incident_window": {"start": iso_from_dt(window_start), "end": iso_from_dt(window_end)}
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2)

    print(json.dumps(payload, indent=2))
    logger.info("Wrote normalized output: %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
