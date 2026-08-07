"""Tests for the Manager Loop."""

import json
import os
from unittest.mock import patch

import pytest

from scripts.manager.manager_loop import (
    fetch_market_drop_pct,
    has_label,
)


def _mock_index_response(today_close: float, prev_close: float, today: str) -> dict:
    """Build a mock TWSE index history response."""
    roc_today = f"{int(today[:4]) - 1911:03d}{today[5:7]}{today[8:10]}"
    roc_prev_date = f"{int(today[:4]) - 1911:03d}{today[5:7]}{int(today[8:10]) - 1:02d}"
    return [
        {
            "Date": roc_prev_date,
            "ClosingIndex": str(prev_close),
        },
        {
            "Date": roc_today,
            "ClosingIndex": str(today_close),
        },
    ]


@patch("scripts.manager.manager_loop.requests.get")
def test_fetch_market_drop_pct(mock_get):
    today = "2026-07-28"
    mock_get.return_value.json.return_value = _mock_index_response(
        10000.0, 10200.0, today
    )
    mock_get.return_value.raise_for_status = lambda: None

    pct = fetch_market_drop_pct(today)
    assert pct == pytest.approx(-1.96, rel=1e-2)


@patch("scripts.manager.manager_loop.requests.get")
def test_fetch_market_drop_pct_market_warning(mock_get):
    today = "2026-07-28"
    mock_get.return_value.json.return_value = _mock_index_response(
        9800.0, 10200.0, today
    )
    mock_get.return_value.raise_for_status = lambda: None

    pct = fetch_market_drop_pct(today)
    assert pct < -2.0


@patch("scripts.manager.manager_loop.requests.get")
def test_fetch_market_drop_pct_missing_today(mock_get):
    today = "2026-07-28"
    mock_get.return_value.json.return_value = _mock_index_response(
        10000.0, 10200.0, "2026-07-27"
    )
    mock_get.return_value.raise_for_status = lambda: None

    pct = fetch_market_drop_pct(today)
    assert pct is None


def test_has_label():
    issue = {"labels": [{"name": "screened"}, {"name": "auto-ok"}]}
    assert has_label(issue, "screened") is True
    assert has_label(issue, "human-review") is False


@patch("scripts.manager.manager_loop._run_gh")
@patch("scripts.manager.manager_loop.fetch_market_drop_pct")
@patch("scripts.manager.manager_loop._today_str")
@patch("scripts.manager.manager_loop._today_compact")
def test_main_writes_report_and_labels_issues(
    mock_compact, mock_today, mock_drop, mock_gh
):
    """Manager labels human-review and guardrail-blocked when both triggers fire."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_drop.return_value = -3.0

    def fake_gh(args):
        result = type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

        if args[1] == "list":
            label = args[args.index("--label") + 1]
            if label == "screened":
                result.stdout = json.dumps(
                    [{"number": 1, "title": "Test", "labels": [{"name": "screened"}]}]
                )
            elif label == "holding":
                result.stdout = json.dumps(
                    [
                        {"number": 10, "title": "H1", "labels": [{"name": "holding"}]},
                        {"number": 11, "title": "H2", "labels": [{"name": "holding"}]},
                        {"number": 12, "title": "H3", "labels": [{"name": "holding"}]},
                        {"number": 13, "title": "H4", "labels": [{"name": "holding"}]},
                        {"number": 14, "title": "H5", "labels": [{"name": "holding"}]},
                        {"number": 15, "title": "H6", "labels": [{"name": "holding"}]},
                    ]
                )
        return result

    mock_gh.side_effect = fake_gh

    from scripts.manager.manager_loop import main

    assert main() == 0

    report_path = "data/manager/manager_report_20260728.json"
    assert os.path.exists(report_path)
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["market_warning_triggered"] is True
    assert report["holding_cap_triggered"] is True
    assert report["current_holding_count"] == 6
    assert report["processed_issue_count"] == 1
    assert report["screened_issue_count"] == 1
    assert report["auto_ok_granted_count"] == 0
    assert report["screened_blocked_count"] == 1

    calls = [call.args[0] for call in mock_gh.call_args_list]
    add_label_calls = [c for c in calls if len(c) > 4 and c[1] == "edit"]
    assert any(c == ["issue", "edit", "1", "--add-label", "human-review"] for c in add_label_calls)
    assert any(
        c == ["issue", "edit", "1", "--add-label", "guardrail-blocked"]
        for c in add_label_calls
    )
    # 護欄觸發時不應核可 auto-ok
    assert not any(c == ["issue", "edit", "1", "--add-label", "auto-ok"] for c in add_label_calls)

    os.remove(report_path)


@patch("scripts.manager.manager_loop._run_gh")
@patch("scripts.manager.manager_loop.fetch_market_drop_pct")
@patch("scripts.manager.manager_loop._today_str")
@patch("scripts.manager.manager_loop._today_compact")
def test_manager_loop_grants_auto_ok_when_guardrails_pass(
    mock_compact, mock_today, mock_drop, mock_gh
):
    """Manager grants auto-ok when market warning is off and holding count is below cap."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_drop.return_value = -1.0  # 未觸發大盤護欄

    def fake_gh(args):
        result = type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        if args[1] == "list":
            label = args[args.index("--label") + 1]
            if label == "screened":
                result.stdout = json.dumps(
                    [{"number": 2, "title": "Test", "labels": [{"name": "screened"}]}]
                )
            elif label == "holding":
                result.stdout = json.dumps([])
        return result

    mock_gh.side_effect = fake_gh

    from scripts.manager.manager_loop import main

    assert main() == 0

    report_path = "data/manager/manager_report_20260728.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["market_warning_triggered"] is False
    assert report["holding_cap_triggered"] is False
    assert report["screened_issue_count"] == 1
    assert report["auto_ok_granted_count"] == 1
    assert report["screened_blocked_count"] == 0

    calls = [call.args[0] for call in mock_gh.call_args_list]
    assert any(c == ["issue", "edit", "2", "--add-label", "auto-ok"] for c in calls)

    os.remove(report_path)


@patch("scripts.manager.manager_loop._run_gh")
@patch("scripts.manager.manager_loop.fetch_market_drop_pct")
@patch("scripts.manager.manager_loop._today_str")
@patch("scripts.manager.manager_loop._today_compact")
def test_manager_loop_blocks_auto_ok_on_market_warning(
    mock_compact, mock_today, mock_drop, mock_gh
):
    """Manager does not grant auto-ok when market drop warning triggers."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_drop.return_value = -3.0  # 觸發大盤護欄

    def fake_gh(args):
        result = type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        if args[1] == "list":
            label = args[args.index("--label") + 1]
            if label == "screened":
                result.stdout = json.dumps(
                    [{"number": 3, "title": "Test", "labels": [{"name": "screened"}]}]
                )
            elif label == "holding":
                result.stdout = json.dumps([])
        return result

    mock_gh.side_effect = fake_gh

    from scripts.manager.manager_loop import main

    assert main() == 0

    report_path = "data/manager/manager_report_20260728.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["market_warning_triggered"] is True
    assert report["screened_issue_count"] == 1
    assert report["auto_ok_granted_count"] == 0
    assert report["screened_blocked_count"] == 1

    calls = [call.args[0] for call in mock_gh.call_args_list]
    assert not any(c == ["issue", "edit", "3", "--add-label", "auto-ok"] for c in calls)

    os.remove(report_path)


@patch("scripts.manager.manager_loop._run_gh")
@patch("scripts.manager.manager_loop.fetch_market_drop_pct")
@patch("scripts.manager.manager_loop._today_str")
@patch("scripts.manager.manager_loop._today_compact")
def test_manager_loop_blocks_auto_ok_on_holding_cap(
    mock_compact, mock_today, mock_drop, mock_gh
):
    """Manager does not grant auto-ok when holding count reaches cap."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_drop.return_value = -1.0  # 未觸發大盤護欄

    def fake_gh(args):
        result = type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        if args[1] == "list":
            label = args[args.index("--label") + 1]
            if label == "screened":
                result.stdout = json.dumps(
                    [{"number": 4, "title": "Test", "labels": [{"name": "screened"}]}]
                )
            elif label == "holding":
                result.stdout = json.dumps(
                    [{"number": i, "title": f"H{i}", "labels": [{"name": "holding"}]}
                     for i in range(10, 16)]
                )
        return result

    mock_gh.side_effect = fake_gh

    from scripts.manager.manager_loop import main

    assert main() == 0

    report_path = "data/manager/manager_report_20260728.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["holding_cap_triggered"] is True
    assert report["screened_issue_count"] == 1
    assert report["auto_ok_granted_count"] == 0
    assert report["screened_blocked_count"] == 1

    calls = [call.args[0] for call in mock_gh.call_args_list]
    assert not any(c == ["issue", "edit", "4", "--add-label", "auto-ok"] for c in calls)

    os.remove(report_path)
