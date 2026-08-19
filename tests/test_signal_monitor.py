"""Tests for the Signal Monitor."""

import glob
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from scripts.monitor.signal_monitor import (
    check_entry_signal,
    compute_foreign_buy_streak_day,
    compute_price_metrics,
    count_trading_days_after_breakout,
    evaluate_signals,
    parse_entry_info,
)


def _make_history(closes: list[float], turnover: list[float] | None = None) -> list[dict]:
    if turnover is None:
        turnover = [0.0] * len(closes)
    return [
        {"date": f"11507{i + 1:02d}", "close": c, "high": c, "low": c, "turnover": t}
        for i, (c, t) in enumerate(zip(closes, turnover))
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


@patch("scripts.monitor.signal_monitor.compute_price_metrics")
@patch("scripts.monitor.signal_monitor.fetch_stock_history")
def test_fetch_price_metrics_uses_local_stock_history(mock_history, mock_compute):
    """Local fetch_price_metrics should use the reliable exchangeReport endpoint."""
    mock_history.return_value = [{"close": 100.0}] * 25
    mock_compute.return_value = {
        "close": 110.0,
        "ma5": 105.0,
        "ma20": 100.0,
    }

    from scripts.monitor.signal_monitor import fetch_price_metrics

    result = fetch_price_metrics("2330", "20260728")
    assert result == {"close": 110.0, "ma5": 105.0, "ma20": 100.0}
    mock_history.assert_called_once_with("2330", "20260728")


@patch("scripts.monitor.signal_monitor.compute_price_metrics")
@patch("scripts.monitor.signal_monitor.fetch_stock_history")
def test_fetch_price_metrics_returns_none_when_history_unavailable(mock_history, mock_compute):
    mock_history.return_value = None
    from scripts.monitor.signal_monitor import fetch_price_metrics
    assert fetch_price_metrics("2330", "20260728") is None
    mock_compute.assert_not_called()


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


def _make_raw_data_with_dates(
    ticker: str, foreign_nets: list[float], trust_nets: list[float], dates: list[str]
) -> list:
    records = []
    for date_str, fn, tn in zip(dates, foreign_nets, trust_nets):
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


def _date_range_compact(start: str, end: str) -> list[str]:
    """Return compact YYYYMMDD dates from start to end inclusive."""
    start_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# Oracle-based tests for Setup B / C entry and exit signals
# ---------------------------------------------------------------------------


def _entry_oracle_paths(setup: str) -> list[tuple[str, str]]:
    """Return (input_path, output_path) pairs for Setup B/C entry oracles."""
    inputs = sorted(
        glob.glob(f"tests/fixtures/oracle_signal_{setup}_entry_input_????-??-??.json")
    )
    pairs = []
    for inp in inputs:
        out = inp.replace("_input_", "_output_")
        pairs.append((inp, out))
    return pairs


def _exit_oracle_paths(setup: str) -> list[tuple[str, str]]:
    """Return (input_path, output_path) pairs for Setup B/C exit oracles."""
    inputs = sorted(
        glob.glob(f"tests/fixtures/oracle_signal_{setup}_exit_input_????-??-??.json")
    )
    pairs = []
    for inp in inputs:
        out = inp.replace("_input_", "_output_")
        pairs.append((inp, out))
    return pairs


@pytest.mark.parametrize("input_path,output_path", _entry_oracle_paths("b"))
def test_setup_b_entry_oracle(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    breakout_date = oracle_input["breakout_date"]
    breakout_price = oracle_input["breakout_price"]
    breakout_volume_m = oracle_input["breakout_volume_m"]

    for case, expected in zip(oracle_input["cases"], oracle_output["cases"]):
        today_date = case["today_date"].replace("-", "")
        raw_dates = [d.replace("-", "") for d in oracle_input.get("raw_dates", [])]
        if not raw_dates:
            raw_dates = _date_range_compact(
                breakout_date.replace("-", ""), today_date
            )
        raw_data = _make_raw_data_with_dates(
            "2330",
            [1.0] * len(raw_dates),
            [1.0] * len(raw_dates),
            raw_dates,
        )

        def fake_fetch_stock_history(ticker: str, date: str) -> list[dict]:
            # Provide just enough history for compute_price_metrics.
            return _make_history(
                [100.0] * 24 + [case["close"]],
                turnover=[0.0] * 24 + [case["volume_m"] * 1_000_000],
            )

        with patch(
            "scripts.monitor.signal_monitor.fetch_price_metrics",
            return_value={"close": case["close"], "ma5": 100.0, "ma20": 100.0},
        ), patch(
            "scripts.monitor.signal_monitor.fetch_stock_history",
            side_effect=fake_fetch_stock_history,
        ):
            signal = check_entry_signal(
                "2330",
                today_date,
                setup_type="b",
                issue_info={
                    "breakout_date": breakout_date,
                    "breakout_price": breakout_price,
                    "breakout_volume_m": breakout_volume_m,
                },
                raw_data=raw_data,
            )

        assert signal is not None, case["name"]
        expected_confirmed = expected.get(
            "entry_confirmed", case.get("expected_entry_confirmed")
        )
        assert signal["triggered"] == expected_confirmed, case["name"]


@pytest.mark.parametrize("input_path,output_path", _entry_oracle_paths("c"))
def test_setup_c_entry_oracle(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    for case, expected in zip(oracle_input["cases"], oracle_output["cases"]):
        today_date = "20260801"  # compact date used by fetch_price_metrics mock

        def fake_fetch_stock_history(ticker: str, date: str) -> list[dict]:
            closes = [100.0] * 24 + [case["close"]]
            turnover = [0.0] * 24 + [1_000_000]
            return [
                {
                    "date": f"11507{i + 1:02d}",
                    "close": c,
                    "high": case["today_high"] if i == len(closes) - 1 else c,
                    "low": case["today_low"] if i == len(closes) - 1 else c,
                    "turnover": t,
                }
                for i, (c, t) in enumerate(zip(closes, turnover))
            ]

        with patch(
            "scripts.monitor.signal_monitor.compute_foreign_buy_streak_day",
            return_value=case["foreign_buy_streak_day"],
        ), patch(
            "scripts.monitor.signal_monitor.fetch_price_metrics",
            return_value={"close": case["close"], "ma5": 100.0, "ma20": 100.0},
        ), patch(
            "scripts.monitor.signal_monitor.fetch_stock_history",
            side_effect=fake_fetch_stock_history,
        ):
            signal = check_entry_signal(
                "2330",
                today_date,
                setup_type="c",
                raw_data=[],  # streak is mocked
            )

        assert signal is not None, case["name"]
        expected_confirmed = expected.get(
            "entry_confirmed", case.get("expected_entry_confirmed")
        )
        expected_zone = expected.get("entry_zone", case.get("expected_entry_zone"))
        assert signal["triggered"] == expected_confirmed, case["name"]
        assert signal["entry_zone"] == expected_zone, case["name"]


@pytest.mark.parametrize("input_path,output_path", _exit_oracle_paths("b"))
def test_setup_b_exit_oracle(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    cases = oracle_input.get("cases", [oracle_input])
    expected_cases = oracle_output.get("cases", [oracle_output])

    for case, expected in zip(cases, expected_cases):
        metrics = {
            "close": case["close"],
            "ma10": case.get("ma10"),
            "recent_low_20d": case.get("recent_low_20d"),
        }
        nets = case["trust_net_last_2d"]
        raw_data = _make_raw_data_with_dates(
            "2330",
            [1.0] * len(nets),
            nets,
            [f"202607{26 + i:02d}" for i in range(len(nets))],
        )
        result = evaluate_signals(
            "b",
            case["entry_price"],
            "2026-07-01",
            metrics,
            raw_data,
            "2330",
            "2026-07-28",
        )

        assert result["pnl_pct"] == expected["pnl_pct"], case.get("name", "")
        assert result["partial_signals"] == expected["partial_signals"], case.get(
            "name", ""
        )
        assert result["exit_signals"] == expected["exit_signals"], case.get("name", "")
        assert result["stoploss_triggered"] == expected["stoploss_triggered"], case.get(
            "name", ""
        )


@pytest.mark.parametrize("input_path,output_path", _exit_oracle_paths("c"))
def test_setup_c_exit_oracle(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    cases = oracle_input.get("cases", [oracle_input])
    expected_cases = oracle_output.get("cases", [oracle_output])

    for case, expected in zip(cases, expected_cases):
        metrics = {
            "close": case["close"],
            "recent_low_10d": case.get("recent_low_10d"),
        }
        nets = case["foreign_net_last_2d"]
        raw_data = _make_raw_data_with_dates(
            "2330",
            nets,
            [1.0] * len(nets),
            [f"202607{26 + i:02d}" for i in range(len(nets))],
        )
        result = evaluate_signals(
            "c",
            case["entry_price"],
            "2026-07-01",
            metrics,
            raw_data,
            "2330",
            "2026-07-28",
        )

        assert result["pnl_pct"] == expected["pnl_pct"], case.get("name", "")
        assert result["exit_signals"] == expected["exit_signals"], case.get("name", "")
        assert result["stoploss_triggered"] == expected["stoploss_triggered"], case.get(
            "name", ""
        )
        assert result["stopprofit_reminder"] == expected[
            "stopprofit_reminder"
        ], case.get("name", "")


def test_compute_foreign_buy_streak_day_counts_consecutive_positive():
    raw_data = _make_raw_data_with_dates(
        "2330",
        [10.0, 20.0, -5.0, 30.0],
        [0.0, 0.0, 0.0, 0.0],
        ["20260725", "20260726", "20260727", "20260728"],
    )
    # Most recent day (20260728) is positive; streak is 1.
    assert compute_foreign_buy_streak_day(raw_data, "2330") == 1

    raw_data = _make_raw_data_with_dates(
        "2330",
        [-5.0, 10.0, 20.0, 30.0],
        [0.0, 0.0, 0.0, 0.0],
        ["20260725", "20260726", "20260727", "20260728"],
    )
    assert compute_foreign_buy_streak_day(raw_data, "2330") == 3


def test_count_trading_days_after_breakout_excludes_breakout_date():
    raw_data = _make_raw_data_with_dates(
        "2330",
        [1.0, 1.0, 1.0],
        [1.0, 1.0, 1.0],
        ["20260730", "20260731", "20260801"],
    )
    assert count_trading_days_after_breakout(raw_data, "20260731", "20260801") == 1
    assert count_trading_days_after_breakout(raw_data, "20260731", "20260802") == 1
