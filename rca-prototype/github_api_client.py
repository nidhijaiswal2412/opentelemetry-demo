#!/usr/bin/env python3
"""
Minimal GitHub REST API client used by the rca-prototype.
- Reads GITHUB_TOKEN from the environment (required).
- Implements timeouts, retries, pagination, and simple error handling.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    pass


class GitHubClient:
    def __init__(self, org: str, repo: str, token: Optional[str] = None, timeout: int = 10):
        token = token or os.getenv("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError("GITHUB_TOKEN environment variable is required (do not hardcode).")

        self.org = org
        self.repo = repo
        self.base = f"{GITHUB_API_BASE}/repos/{org}/{repo}"
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "rca-prototype/1.0",
        })

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _request(self, method: str, path: str, params: Dict[str, Any] = None) -> Tuple[int, Any, Dict[str, Any]]:
        url = f"{self.base}{path}"
        try:
            resp = self.session.request(method, url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as e:
            logger.error("Request failed: %s", e)
            raise GitHubAPIError(f"Request failed: {e}")

        status = resp.status_code
        headers = dict(resp.headers)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text

        if status >= 400:
            msg = body.get("message") if isinstance(body, dict) else str(body)
            raise GitHubAPIError(f"{method} {url} -> {status}: {msg}")

        return status, body, headers

    def get_repository(self) -> Dict[str, Any]:
        status, data, _ = self._request("GET", "")
        return {"status": status, "data": data}

    def get_commit(self, sha: str) -> Dict[str, Any]:
        status, data, _ = self._request("GET", f"/commits/{sha}")
        return data

    def list_commits(self, since_iso: Optional[str] = None, per_page: int = 100) -> List[Dict[str, Any]]:
        path = "/commits"
        commits: List[Dict[str, Any]] = []
        page = 1
        while True:
            params = {"per_page": per_page, "page": page}
            if since_iso:
                params["since"] = since_iso
            _, data, _ = self._request("GET", path, params=params)
            if not isinstance(data, list):
                break
            commits.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return commits

    def list_workflows(self, per_page: int = 100) -> List[Dict[str, Any]]:
        _, data, _ = self._request("GET", "/actions/workflows", params={"per_page": per_page})
        if isinstance(data, dict):
            return data.get("workflows", [])
        return []

    def list_workflow_runs(self, per_page: int = 100, **filters) -> List[Dict[str, Any]]:
        runs: List[Dict[str, Any]] = []
        page = 1
        while True:
            params = {"per_page": per_page, "page": page}
            params.update(filters)
            _, data, _ = self._request("GET", "/actions/runs", params=params)
            items = data.get("workflow_runs", []) if isinstance(data, dict) else []
            runs.extend(items)
            if len(items) < per_page:
                break
            page += 1
        return runs

    def list_jobs_for_run(self, run_id: int, per_page: int = 100) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        page = 1
        while True:
            _, data, _ = self._request("GET", f"/actions/runs/{run_id}/jobs", params={"per_page": per_page, "page": page})
            items = data.get("jobs", []) if isinstance(data, dict) else []
            jobs.extend(items)
            if len(items) < per_page:
                break
            page += 1
        return jobs

    def list_deployments(self, per_page: int = 100) -> List[Dict[str, Any]]:
        deployments: List[Dict[str, Any]] = []
        page = 1
        while True:
            _, data, _ = self._request("GET", "/deployments", params={"per_page": per_page, "page": page})
            if not isinstance(data, list):
                break
            deployments.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return deployments

    def list_deployment_statuses(self, deployment_id: int) -> List[Dict[str, Any]]:
        _, data, _ = self._request("GET", f"/deployments/{deployment_id}/statuses")
        return data if isinstance(data, list) else []
