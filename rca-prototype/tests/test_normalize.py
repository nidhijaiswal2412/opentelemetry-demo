import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (
    collect_related_services,
    filter_by_window,
    infer_service_from_paths,
    map_evidence_to_services,
)

def test_filter_by_window():
    window_start = "2026-10-15T03:00:00Z"
    window_end = "2026-10-15T04:00:00Z"
    items = [
        {"created_at": "2026-10-15T02:30:00Z"},
        {"created_at": "2026-10-15T03:22:04Z"},
        {"created_at": "2026-10-15T03:55:00Z"},
        {"created_at": "2026-10-15T06:00:00Z"},
    ]
    result = filter_by_window(items, __import__("datetime").datetime.fromisoformat(window_start.replace("Z", "+00:00")), __import__("datetime").datetime.fromisoformat(window_end.replace("Z", "+00:00")))
    assert len(result) == 2
    assert result[0]["created_at"] == "2026-10-15T03:22:04Z"


def test_dependency_graph_for_checkout():
    graph = {
        "checkout": {"upstream": ["frontend", "load-generator"], "downstream": ["payment", "currency", "shipping", "product-catalog", "flagd"]},
        "frontend": {"upstream": ["frontend-proxy"], "downstream": ["checkout"]},
        "payment": {"upstream": ["checkout"], "downstream": ["flagd"]},
        "flagd": {"upstream": ["checkout", "payment"], "downstream": []},
        "load-generator": {"upstream": [], "downstream": ["checkout"]},
    }
    related = collect_related_services("checkout", graph, depth=2)
    assert "frontend" in related["upstream"]
    assert "payment" in related["downstream"]
    assert "flagd" in related["downstream"]

def test_infer_checkout_service_from_path():
    paths = ["src/checkout/CheckoutService.java"]
    services = {"checkout", "frontend", "payment"}

    assert infer_service_from_paths(paths, services) == "checkout"


def test_infer_payment_service_from_path():
    paths = ["payment/PaymentService.java"]
    services = {"checkout", "frontend", "payment"}

    assert infer_service_from_paths(paths, services) == "payment"


def test_infer_frontend_service_from_path():
    paths = ["frontend/src/app.ts"]
    services = {"checkout", "frontend", "payment"}

    assert infer_service_from_paths(paths, services) == "frontend"


def test_map_commit_evidence_to_service():
    class FakeGitHubClient:
        def __init__(self):
            self.calls = 0

        def get_commit(self, sha):
            self.calls += 1
            return {
                "files": [
                    {"filename": "src/checkout/CheckoutService.java"}
                ]
            }

    client = FakeGitHubClient()
    evidence = [
        {
            "source": "github-commit",
            "commitSha": "abc123",
            "message": "Fix checkout error handling",
        }
    ]

    result = map_evidence_to_services(
        evidence,
        ["checkout", "payment", "frontend"],
        client,
    )

    assert len(result["checkout"]) == 1
    assert result["checkout"][0]["commitSha"] == "abc123"
    assert result["payment"] == []
    assert result["frontend"] == []
    assert client.calls == 1
