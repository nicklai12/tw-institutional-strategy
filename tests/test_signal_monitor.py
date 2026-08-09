"""Tests for the Signal Monitor."""

import json
import os
from unittest.mock import patch

import pytest

from scripts.monitor.signal_monitor import (
    check_entry_signal,
    compute_price_metrics,
    evaluate_signals,
    parse_entry_info,
)


def _make_history(closes: list[float]) -> list[dict]:
    return [
        {"date": f"11507{i + 1:02d}", "close": c, "high": c, "low": c}
        for i, c in enumerate(closes)
    ]


def _make_raw_data(ticker: str, foreign_nets: list[float], trust_nets: list[float]) -> list:
    base_date = 20260701
    records = []
    for i, (fn, tn) in enumerate(zip(foreign_nets, trust_nets)):
        date_str = str(base_date + i)
        records.append(
            (
                date_str,
                {
                    "data": [
                        {
                            "ticker": ticker,
                            "foreign_net": fn,
                            "trust_net": tn,
                        }
                    ]
                },
            )
        )
    return records


def test_parse_entry_info_from_body_and_comments():
    issue = {
        "title": "[Setup-A][20260727] 2330 台積電",
        "body": "- **ticker**: 2330\n- **entry_date**: 2026-07-28\n- **entry_price**: 500.0",
        "labels": [{"name": "setup-a"}],
        "comments": [
            {
                "createdAt": "2026-07-28T10:00:00Z",
                "body": "- **setup_type**: a\n- **entry_price**: 510.0",
            }
        ],
    }
    info = parse_entry_info(issue)
    assert info["ticker"] == "2330"
    assert info["setup_type"] == "a"
    assert info["entry_date"] == "2026-07-28"
    assert info["entry_price"] == 500.0  # body wins over older comment


def test_compute_price_metrics():
    closes = [100.0 + i for i in range(25)]
    history = _make_history(closes)
    metrics = compute_price_metrics(history)
    assert metrics["close"] == 124.0
    assert metrics["ma20"] == 114.5
    assert metrics["ma10"] == 119.5
    assert metrics["ma20_close_direction"] == "站上"


def test_setup_a_exit_e1_foreign_weak():
    history = _make_history([100.0] * 25)
    raw = _make_raw_data("2330", [5.0, -1.0, -2.0, -3.0], [1.0, 2.0, 3.0, 4.0])
    metrics = compute_price_metrics(history)
    result = evaluate_signals("a", 100.0, "2026-07-01", metrics, raw, "2330", "2026-07-04")
    assert "E1 法人轉弱" in result["exit_signals"]


def test_setup_a_exit_e2_price_weak():
    # closes rise then drop below MA20 for last two days
    closes = [100.0 + i for i in range(20)] + [90.0, 85.0]
    history = _make_history(closes)
    raw = _make_raw_data("2330", [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])
    metrics = compute_price_metrics(history)
    assert metrics["today_close_below_ma20"] is True
    assert metrics["prev_close_below_ma20"] is True
    result = evaluate_signals("a", 100.0, "2026-07-01", metrics, raw, "2330", "2026-07-22")
    assert "E2 價格轉弱" in result["exit_signals"]


def test_setup_a_stop_loss():
    history = _make_history([90.0] * 25)
    raw = _make_raw_data("2330", [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])
    metrics = compute_price_metrics(history)
    result = evaluate_signals("a", 100.0, "2026-07-01", metrics, raw, "2330", "2026-07-22")
    assert result["stoploss_triggered"] is True
    assert result["pnl_pct"] == -10.0


def test_setup_b_partial_and_full_exit():
    # Close below MA10 and recent low; trust sells 2 days
    closes = [100.0 + i for i in range(15)] + [90.0, 85.0]
    history = _make_history(closes)
    raw = _make_raw_data("2330", [1.0, 2.0, 3.0, 4.0], [1.0, -2.0, -3.0, -4.0])
    metrics = compute_price_metrics(history)
    result = evaluate_signals("b", 100.0, "2026-07-01", metrics, raw, "2330", "2026-07-17")
    assert any("E1" in s for s in result["partial_signals"])
    assert any("E2" in s for s in result["exit_signals"])


def test_setup_c_exit_and_stop_profit_reminder():
    closes = [108.0] * 25  # 8% gain
    history = _make_history(closes)
    raw = _make_raw_data("2330", [1.0, -1.0, -2.0, -3.0], [1.0, 2.0, 3.0, 4.0])
    metrics = compute_price_metrics(history)
    result = evaluate_signals("c", 100.0, "2026-07-01", metrics, raw, "2330", "2026-07-25")
    assert "E1 外資連續轉賣" in result["exit_signals"]
    assert result["stopprofit_reminder"] is True


@patch("scripts.monitor.signal_monitor._run_gh")
@patch("scripts.monitor.signal_monitor.fetch_stock_history")
@patch("scripts.monitor.signal_monitor.get_issue_details")
@patch("scripts.monitor.signal_monitor.get_holding_issues")
@patch("scripts.monitor.signal_monitor.load_raw_files")
@patch("scripts.monitor.signal_monitor._today_str")
@patch("scripts.monitor.signal_monitor._today_compact")
def test_main_reports_stoploss_without_labeling(
    mock_compact,
    mock_today,
    mock_raw,
    mock_holding,
    mock_details,
    mock_history,
    mock_gh,
):
    """Signal monitor records stop loss in report but no longer applies exit labels."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_raw.return_value = _make_raw_data(
        "2330", [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]
    )
    mock_holding.return_value = [{"number": 42, "title": "H", "labels": []}]
    mock_details.return_value = {
        "number": 42,
        "title": "[Setup-A][20260727] 2330 台積電",
        "body": "- **entry_date**: 2026-07-27\n- **entry_price**: 100.0\n- **setup_type**: a",
        "labels": [{"name": "setup-a"}, {"name": "holding"}],
        "comments": [],
    }
    mock_history.return_value = _make_history([90.0] * 25)

    def fake_gh(args):
        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    mock_gh.side_effect = fake_gh

    from scripts.monitor.signal_monitor import main

    assert main() == 0

    report_path = "data/monitor/monitor_report_20260728.json"
    assert os.path.exists(report_path)
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    # 現有欄位保留：exit_signals / stoploss_triggered / partial_signals 仍存在 report 中
    assert "exit_signals" in report["holdings"][0]
    assert "stoploss_triggered" in report["holdings"][0]
    assert "partial_signals" in report["holdings"][0]
    assert report["holdings"][0]["stoploss_triggered"] is True

    # signal_monitor 不再對 exit-triggered / result-stoploss-hit / holding 進行 Label 操作
    calls = [call.args[0] for call in mock_gh.call_args_list]
    edit_calls = [c for c in calls if c[1] == "edit"]
    assert not any(
        c == ["issue", "edit", "42", "--add-label", "exit-triggered"]
        for c in edit_calls
    )
    assert not any(
        c == ["issue", "edit", "42", "--add-label", "result-stoploss-hit"]
        for c in edit_calls
    )
    assert not any(
        c == ["issue", "edit", "42", "--remove-label", "holding"]
        for c in edit_calls
    )

    os.remove(report_path)


def test_check_entry_signal_returns_none_when_metrics_unavailable():
    with patch("scripts.monitor.signal_monitor.fetch_price_metrics", return_value=None):
        signal = check_entry_signal("2330", "20260728")
    assert signal is None


@patch("scripts.monitor.signal_monitor.fetch_price_metrics")
def test_check_entry_signal_with_mocked_metrics(mock_fetch):
    mock_fetch.return_value = {"close": 105.0, "ma5": 100.0, "ma20": 110.0}
    signal = check_entry_signal("2330", "20260728")
    assert signal is not None
    assert signal["triggered"] is True
    assert signal["close"] == 105.0
    assert signal["ma5"] == 100.0
    assert signal["ma20"] == 110.0
    assert signal["lower"] == 100.0
    assert signal["upper"] == 110.0


@patch("scripts.monitor.signal_monitor.fetch_price_metrics")
def test_check_entry_signal_not_triggered_when_close_outside_zone(mock_fetch):
    mock_fetch.return_value = {"close": 95.0, "ma5": 100.0, "ma20": 110.0}
    signal = check_entry_signal("2330", "20260728")
    assert signal is not None
    assert signal["triggered"] is False


@patch("scripts.monitor.signal_monitor._run_gh")
@patch("scripts.monitor.signal_monitor.fetch_price_metrics")
@patch("scripts.monitor.signal_monitor.get_issue_details")
@patch("scripts.monitor.signal_monitor.get_auto_ok_issues")
@patch("scripts.monitor.signal_monitor.get_holding_issues")
@patch("scripts.monitor.signal_monitor.load_raw_files")
@patch("scripts.monitor.signal_monitor._today_str")
@patch("scripts.monitor.signal_monitor._today_compact")
def test_main_entry_signal_confirms_auto_ok_issue(
    mock_compact,
    mock_today,
    mock_raw,
    mock_holding,
    mock_auto_ok,
    mock_details,
    mock_fetch,
    mock_gh,
):
    """When close is inside MA5/MA20 zone, labels move screened/auto-ok -> signal-confirmed."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_raw.return_value = _make_raw_data(
        "2330", [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]
    )
    mock_holding.return_value = []
    mock_auto_ok.return_value = [{"number": 77, "title": "[Setup-A][20260727] 2330 台積電", "labels": []}]
    mock_details.return_value = {
        "number": 77,
        "title": "[Setup-A][20260727] 2330 台積電",
        "body": "- **ticker**: 2330\n- **entry_zone**: 100.00-110.00",
        "labels": [{"name": "setup-a"}, {"name": "screened"}, {"name": "auto-ok"}],
        "comments": [],
    }
    mock_fetch.return_value = {"close": 105.0, "ma5": 100.0, "ma20": 110.0}

    def fake_gh(args):
        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    mock_gh.side_effect = fake_gh

    from scripts.monitor.signal_monitor import main

    assert main() == 0

    calls = [call.args[0] for call in mock_gh.call_args_list]
    edit_calls = [c for c in calls if len(c) > 1 and c[1] == "edit"]
    comment_calls = [c for c in calls if len(c) > 1 and c[1] == "comment"]

    assert any(
        c == ["issue", "edit", "77", "--remove-label", "screened", "--remove-label", "auto-ok", "--add-label", "signal-confirmed"]
        for c in edit_calls
    ), f"Expected label edit not found in {edit_calls}"
    assert len(comment_calls) == 1
    comment_args = comment_calls[0]
    body_index = comment_args.index("--body") + 1
    comment_body = comment_args[body_index]
    assert "105.0" in comment_body
    assert "100.0" in comment_body
    assert "110.0" in comment_body
    assert "100.00-110.00" in comment_body
    assert "訊號確認，符合進場條件" in comment_body

    report_path = "data/monitor/monitor_report_20260728.json"
    if os.path.exists(report_path):
        os.remove(report_path)


@patch("scripts.monitor.signal_monitor._run_gh")
@patch("scripts.monitor.signal_monitor.fetch_price_metrics")
@patch("scripts.monitor.signal_monitor.get_issue_details")
@patch("scripts.monitor.signal_monitor.get_auto_ok_issues")
@patch("scripts.monitor.signal_monitor.get_holding_issues")
@patch("scripts.monitor.signal_monitor.load_raw_files")
@patch("scripts.monitor.signal_monitor._today_str")
@patch("scripts.monitor.signal_monitor._today_compact")
def test_main_entry_signal_no_label_change_when_not_triggered(
    mock_compact,
    mock_today,
    mock_raw,
    mock_holding,
    mock_auto_ok,
    mock_details,
    mock_fetch,
    mock_gh,
):
    """When close is outside MA5/MA20 zone, no label changes occur."""
    mock_today.return_value = "2026-07-28"
    mock_compact.return_value = "20260728"
    mock_raw.return_value = _make_raw_data(
        "2330", [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]
    )
    mock_holding.return_value = []
    mock_auto_ok.return_value = [{"number": 78, "title": "[Setup-A][20260727] 2330 台積電", "labels": []}]
    mock_details.return_value = {
        "number": 78,
        "title": "[Setup-A][20260727] 2330 台積電",
        "body": "- **ticker**: 2330\n- **entry_zone**: 100.00-110.00",
        "labels": [{"name": "setup-a"}, {"name": "screened"}, {"name": "auto-ok"}],
        "comments": [],
    }
    mock_fetch.return_value = {"close": 95.0, "ma5": 100.0, "ma20": 110.0}

    def fake_gh(args):
        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    mock_gh.side_effect = fake_gh

    from scripts.monitor.signal_monitor import main

    assert main() == 0

    calls = [call.args[0] for call in mock_gh.call_args_list]
    edit_calls = [c for c in calls if len(c) > 1 and c[1] == "edit"]
    comment_calls = [c for c in calls if len(c) > 1 and c[1] == "comment"]

    assert not any("signal-confirmed" in c for c in edit_calls)
    assert not any("--remove-label" in c for c in edit_calls)
    assert len(comment_calls) == 0

    report_path = "data/monitor/monitor_report_20260728.json"
    if os.path.exists(report_path):
        os.remove(report_path)
