
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalize_data import normalize_all


def test_normalize_commit_evidence():
    raw = {
        "commits": [
            {
                "sha": "abc123",
                "html_url": "https://github.com/example/repo/commit/abc123",
                "author": {"login": "test-user"},
                "commit": {
                    "author": {
                        "name": "Test User",
                        "date": "2026-10-15T03:22:00Z",
                    },
                    "committer": {
                        "date": "2026-10-15T03:22:00Z",
                    },
                    "message": "Fix checkout error handling",
                },
            }
        ],
        "runs": [],
        "deployments": [],
        "jobs_by_run": {},
    }

    result = normalize_all(
        service="checkout",
        environment="development",
        org="example",
        repo="repo",
        raw=raw,
    )

    evidence = result["evidence"]

    assert len(evidence) == 1
    assert evidence[0]["source"] == "github-commit"
    assert evidence[0]["commitSha"] == "abc123"
    assert evidence[0]["author"] == "Test User"
    assert evidence[0]["committedAt"] == "2026-10-15T03:22:00Z"
    assert evidence[0]["message"] == "Fix checkout error handling"
    assert evidence[0]["url"] == "https://github.com/example/repo/commit/abc123"
