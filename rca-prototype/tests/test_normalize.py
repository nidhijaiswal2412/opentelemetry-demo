import pytest
from normalize_data import normalize_all

def test_normalize_minimal():
    raw = {
        "repository": {"full_name": "org/repo"},
        "commits": [{"sha": "abc123", "commit": {"author": {"name": "Alice"}}}],
        "runs": [
            {
                "id": 1,
                "name": "CI",
                "head_sha": "abc123",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-10-15T00:00:00Z",
                "updated_at": "2026-10-15T00:05:00Z",
                "actor": {"login": "alice"},
                "html_url": "https://github.com/org/repo/actions/runs/1",
            }
        ],
        "jobs_by_run": {"1": [{"id": 11, "name": "build", "status": "completed", "conclusion": "success", "started_at": "2026-10-15T00:00:00Z", "completed_at": "2026-10-15T00:04:00Z", "html_url": "https://..."}]},
        "deployments": [],
        "deployment_statuses": {}
    }
    out = normalize_all("svc", "dev", "org", "repo", raw)
    assert out["service"] == "svc"
    assert out["environment"] == "dev"
    assert out["repository"] == "org/repo"
    assert isinstance(out["evidence"], list)
    assert out["evidence"][0]["buildId"] == 1
    assert out["evidence"][0]["commitSha"] == "abc123"
