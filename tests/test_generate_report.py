"""Tests for the weekly Report Agent."""

import json
import os
from datetime import date
from unittest.mock import patch

import pytest

from scripts.report.generate_report import (
    _build_report,
    _compute_current_holdings,
    _compute_strategy_performance,
    _compute_system_health,
    _count_guardrail_triggers,
    _parse_pnl_from_comments,
)


def _make_issue(
    number: int,
    title: str,
    labels: list[str],
    created_at: str = "2026-07-21T10:00:00Z",
    body: str = "",
    comments: list[dict] | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "labels": [{"name": name} for name in labels],
        "createdAt": created_at,
        "body": body,
        "comments": comments or [],
    }


def test_parse_pnl_from_comments_returns_latest_value():
    issue = {
        "comments": [
            {"body": "- 相對進場損益：1.5%"},
            {"body": "- 相對進場損益：-2.3%"},
        ]
    }
    assert _parse_pnl_from_comments(issue) == "-2.3"


def test_parse_pnl_from_comments_returns_none_when_missing():
    issue = {"comments": [{"body": "some unrelated text"}]}
    assert _parse_pnl_from_comments(issue) is None


def test_compute_strategy_performance_with_three_closed_issues():
    issues = [
        _make_issue(1, "[Setup-A][20260721] 2330", ["setup-a", "closed", "result-profit"]),
        _make_issue(2, "[Setup-A][20260722] 2317", ["setup-a", "closed", "result-loss"]),
        _make_issue(3, "[Setup-B][20260723] 2454", ["setup-b", "closed", "result-stoploss-hit"]),
    ]
    perf = _compute_strategy_performance(issues)

    assert perf["setup_a"] == {
        "closed_count": 2,
        "win_count": 1,
        "lose_count": 1,
        "stoploss_count": 0,
        "win_rate": 0.5,
    }
    assert perf["setup_b"] == {
        "closed_count": 1,
        "win_count": 0,
        "lose_count": 0,
        "stoploss_count": 1,
        "win_rate": 0.0,
    }
    assert perf["setup_c"] == {
        "closed_count": 0,
        "win_count": 0,
        "lose_count": 0,
        "stoploss_count": 0,
        "win_rate": 0.0,
    }


def test_compute_strategy_performance_empty_issues():
    perf = _compute_strategy_performance([])
    for setup in ("setup_a", "setup_b", "setup_c"):
        assert perf[setup]["closed_count"] == 0
        assert perf[setup]["win_rate"] == 0.0


def test_compute_system_health_counts_screened_and_human_review():
    issues = [
        _make_issue(1, "A", ["setup-a", "screened"], created_at="2026-07-28T10:00:00+08:00"),
        _make_issue(2, "B", ["setup-a", "screened", "data-missing"], created_at="2026-07-29T10:00:00+08:00"),
        _make_issue(3, "C", ["setup-a", "human-review"], created_at="2026-07-30T10:00:00+08:00"),
        _make_issue(4, "D", ["setup-a", "human-review"], created_at="2026-07-20T10:00:00+08:00"),
    ]
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))
    week_start = datetime(2026, 7, 27, tzinfo=tz)
    week_end = week_start + timedelta(days=7, microseconds=-1)

    health = _compute_system_health(issues, week_start, week_end, guardrail_triggered_count=3)

    assert health["total_screened_this_week"] == 2
    assert health["audit_pass_rate"] == 0.5
    assert health["guardrail_triggered_count"] == 3
    assert health["human_review_count"] == 1


def test_compute_system_health_pass_rate_is_one_when_no_screened():
    issues = []
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))
    week_start = datetime(2026, 7, 27, tzinfo=tz)
    week_end = week_start + timedelta(days=7, microseconds=-1)

    health = _compute_system_health(issues, week_start, week_end, 0)
    assert health["audit_pass_rate"] == 1.0
    assert health["total_screened_this_week"] == 0


def test_compute_current_holdings():
    issues = [
        _make_issue(
            10,
            "[Setup-A][20260721] 2330",
            ["setup-a", "holding"],
            body="- **entry_date**: 2026-07-21",
            comments=[{"body": "- 相對進場損益：5.5%"}],
        ),
        _make_issue(
            11,
            "[Setup-B][20260722] 2317",
            ["setup-b", "holding"],
            body="- **entry_date**: 2026-07-22",
        ),
    ]
    holdings = _compute_current_holdings(issues, date(2026, 7, 31))

    assert holdings["total"] == 2
    assert holdings["by_setup"] == {"a": 1, "b": 1, "c": 0}
    assert holdings["holdings"][0]["days_held"] == 10
    assert holdings["holdings"][0]["pnl_pct"] == "5.5"
    assert holdings["holdings"][1]["pnl_pct"] == "N/A"


@patch("scripts.report.generate_report._count_guardrail_triggers")
@patch("scripts.report.generate_report._this_week_guardrail_artifacts")
@patch("scripts.report.generate_report._list_all_issues")
@patch("scripts.report.generate_report._current_iso_week")
@patch("scripts.report.generate_report._today_taiwan")
def test_main_with_three_closed_issues(
    mock_today, mock_week, mock_issues, mock_artifacts, mock_guardrail_count
):
    """End-to-end: 3 closed issues produce correct report JSON and HTML."""
    mock_today.return_value = date(2026, 7, 31)
    mock_week.return_value = (2026, 30)
    mock_artifacts.return_value = []
    mock_guardrail_count.return_value = 1
    mock_issues.return_value = [
        _make_issue(1, "[Setup-A][20260721] 2330", ["setup-a", "closed", "result-profit"]),
        _make_issue(2, "[Setup-A][20260722] 2317", ["setup-a", "closed", "result-loss"]),
        _make_issue(3, "[Setup-B][20260723] 2454", ["setup-b", "closed", "result-stoploss-hit"]),
    ]

    from scripts.report.generate_report import main

    assert main() == 0

    report_path = "docs/data/report_202630.json"
    assert os.path.exists(report_path)
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    assert report["report_year"] == 2026
    assert report["report_week"] == 30
    assert report["system_health"]["guardrail_triggered_count"] == 1
    assert report["strategy_performance"]["setup_a"]["closed_count"] == 2
    assert report["strategy_performance"]["setup_a"]["win_rate"] == 0.5
    assert report["strategy_performance"]["setup_b"]["stoploss_count"] == 1
    assert report["strategy_performance"]["setup_c"]["closed_count"] == 0

    html_path = "docs/index.html"
    assert os.path.exists(html_path)
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    assert "Setup A" in html
    assert "50%" in html
    assert "免責聲明" in html

    os.remove(report_path)
    os.remove(html_path)


@patch("scripts.report.generate_report._count_guardrail_triggers")
@patch("scripts.report.generate_report._this_week_guardrail_artifacts")
@patch("scripts.report.generate_report._list_all_issues")
@patch("scripts.report.generate_report._current_iso_week")
@patch("scripts.report.generate_report._today_taiwan")
def test_main_with_no_issues(
    mock_today, mock_week, mock_issues, mock_artifacts, mock_guardrail_count
):
    """End-to-end: no issues produce zeros without crashing."""
    mock_today.return_value = date(2026, 7, 31)
    mock_week.return_value = (2026, 30)
    mock_artifacts.return_value = []
    mock_guardrail_count.return_value = 0
    mock_issues.return_value = []

    from scripts.report.generate_report import main

    assert main() == 0

    report_path = "docs/data/report_202630.json"
    assert os.path.exists(report_path)
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    assert report["system_health"]["total_screened_this_week"] == 0
    assert report["system_health"]["audit_pass_rate"] == 1.0
    assert report["system_health"]["guardrail_triggered_count"] == 0
    assert report["system_health"]["human_review_count"] == 0
    for setup in ("setup_a", "setup_b", "setup_c"):
        assert report["strategy_performance"][setup]["closed_count"] == 0
        assert report["strategy_performance"][setup]["win_rate"] == 0.0
    assert report["current_holdings"]["total"] == 0

    html_path = "docs/index.html"
    assert os.path.exists(html_path)

    os.remove(report_path)
    os.remove(html_path)
