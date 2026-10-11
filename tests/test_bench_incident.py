from scripts.bench_incident import percentile, summarize


def test_percentile_nearest_rank():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert percentile([5], 0.95) == 5


def test_summarize_counts_failures_and_safety_net():
    t = lambda tool, o="ok": {"tool": tool, "outcome": o}
    rows = [
        {"scenario": "A", "seconds": 10.0, "ok": True, "tools": [t("kpi_profile"), t("search_runbooks")]},
        {"scenario": "A", "seconds": 20.0, "ok": True, "tools": [t("kpi_profile", "safety_net")]},
        {"scenario": "B", "seconds": 99.0, "ok": False, "tools": []},
    ]
    s = summarize(rows)
    assert s["overall"]["n"] == 3 and s["overall"]["ok"] == 2
    assert s["overall"]["median_s"] == 15.0          # failed run excluded from timing
    assert s["by_scenario"]["B"]["median_s"] is None
    assert s["agent"]["safety_net_share"] == round(1 / 3, 3)
    assert s["agent"]["tool_calls_per_incident"] == 1.5
