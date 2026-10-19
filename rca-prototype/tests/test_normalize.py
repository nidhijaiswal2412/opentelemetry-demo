import pytest

from main import collect_related_services, filter_by_window


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
