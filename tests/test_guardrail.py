"""Tests for the Guardrail checks."""

import datetime
import json
import os
from unittest.mock import patch

import pytest

from scripts.guardrail.pre_run_check import (
    check_api_reachable,
    check_holding_count,
    check_rolling_data,
    check_today_screener_done,
    check_trading_day,
)


@patch("scripts.guardrail.pre_run_check.requests.get")
def test_check_api_reachable(mock_get):
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {"stat": "OK", "data": [["row"]]}
    assert check_api_reachable("20260728") is True


@patch("scripts.guardrail.pre_run_check.requests.get")
def test_check_api_reachable_failure(mock_get):
    mock_get.side_effect = Exception("network down")
    assert check_api_reachable("20260728") is False


@patch("scripts.guardrail.pre_run_check.requests.get")
def test_check_trading_day_ok(mock_get):
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {"stat": "OK", "data": [["row"]]}
    assert check_trading_day("20260728") is True


@patch("scripts.guardrail.pre_run_check.requests.get")
def test_check_trading_day_holiday(mock_get):
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {"stat": "查詢日期無資料", "data": []}
    assert check_trading_day("20260728") is False


def test_check_rolling_data(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.guardrail.pre_run_check._ROLLING_DIR", str(tmp_path)
    )

    # Pin date.today() so the filename check is deterministic.
    class FixedDate:
        @classmethod
        def today(cls):
            return datetime.date(2026, 7, 28)

    monkeypatch.setattr("scripts.guardrail.pre_run_check.date", FixedDate)

    payload = {"fetch_date": "2026-07-28"}
    path = tmp_path / "20260728_rolling.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert check_rolling_data("2026-07-28") is True
    assert check_rolling_data("2026-07-27") is False


@patch("scripts.guardrail.pre_run_check._run_gh")
def test_check_holding_count(mock_gh):
    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps([{"number": 1}, {"number": 2}, {"number": 3}])

    mock_gh.return_value = Result()
    assert check_holding_count() == 3


@patch("scripts.guardrail.pre_run_check._run_gh")
def test_check_today_screener_done(mock_gh):
    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            [
                {"number": 1, "labels": [{"name": "screened"}, {"name": "setup-a"}]},
                {"number": 2, "labels": [{"name": "screened"}, {"name": "setup-a"}]},
                {"number": 3, "labels": [{"name": "screened"}, {"name": "setup-a"}]},
                {"number": 4, "labels": [{"name": "screened"}, {"name": "setup-a"}]},
                {"number": 5, "labels": [{"name": "screened"}, {"name": "setup-a"}]},
            ]
        )

    mock_gh.return_value = Result()
    assert check_today_screener_done("2026-07-28", 5) is True
    assert check_today_screener_done("2026-07-28", 6) is False


@patch("scripts.guardrail.pre_run_check._set_output")
@patch("scripts.guardrail.pre_run_check.requests.get")
def test_main_api_unreachable_exits_1(mock_get, mock_output):
    mock_get.side_effect = Exception("network down")

    from scripts.guardrail.pre_run_check import main

    assert main() == 1


@patch("scripts.guardrail.pre_run_check._set_output")
@patch("scripts.guardrail.pre_run_check.requests.get")
def test_main_non_trading_day_exits_0(mock_get, mock_output):
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {"stat": "查詢日期無資料", "data": []}

    from scripts.guardrail.pre_run_check import main

    assert main() == 0


@patch("scripts.guardrail.pre_run_check._set_output")
@patch("scripts.guardrail.pre_run_check.requests.get")
def test_main_passes(mock_get, mock_output):
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {"stat": "OK", "data": [["row"]]}

    with patch("scripts.guardrail.pre_run_check.check_holding_count", return_value=3), \
         patch("scripts.guardrail.pre_run_check.check_today_screener_done", return_value=False), \
         patch("scripts.guardrail.pre_run_check.check_rolling_data", return_value=True):
        from scripts.guardrail.pre_run_check import main

        assert main() == 0

    mock_output.assert_called_with("passed", "true")
