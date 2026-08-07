"""Tests for the Exit Checker."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/exit-checker 目錄含連字號，無法用標準 import，改用 importlib 載入。
spec = importlib.util.spec_from_file_location(
    "exit_checker_mod", str(Path("scripts/exit-checker/exit_checker.py"))
)
exit_checker_mod = importlib.util.module_from_spec(spec)
sys.modules["exit_checker_mod"] = exit_checker_mod
spec.loader.exec_module(exit_checker_mod)


@pytest.fixture
def tmp_dirs(tmp_path):
    monitor_dir = tmp_path / "monitor"
    report_dir = tmp_path / "exit-checker"
    monitor_dir.mkdir()
    report_dir.mkdir()
    return monitor_dir, report_dir


def _write_monitor_report(monitor_dir: Path, holdings: list[dict]) -> None:
    path = monitor_dir / "monitor_report_20260728.json"
    path.write_text(
        json.dumps(
            {
                "date": "2026-07-28",
                "raw_date": "20260727",
                "processed_count": len(holdings),
                "exit_triggered_count": 0,
                "holdings": holdings,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _make_fake_gh(has_holding: bool = True):
    def fake_gh(args: list[str]):
        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        if args[0] == "run" and args[1] == "download":
            return Result()

        if args[0] == "issue" and args[1] == "view":
            labels = [{"name": "screened"}]
            if has_holding:
                labels.append({"name": "holding"})
            Result.stdout = json.dumps({"labels": labels})
            return Result()

        if args[0] == "issue" and args[1] == "edit":
            return Result()

        return Result()

    return fake_gh


def _run_exit_checker(dry_run: bool = False):
    argv = ["exit_checker.py"]
    if dry_run:
        argv.append("--dry-run")
    with patch.object(sys, "argv", argv):
        return exit_checker_mod.main()


@patch.object(exit_checker_mod, "_run_gh")
@patch.object(exit_checker_mod, "_today_taiwan_compact", return_value="20260728")
@patch.object(exit_checker_mod, "_today_taiwan_str", return_value="2026-07-28")
def test_exit_checker_stoploss_adds_both_labels(
    mock_today, mock_compact, mock_gh, tmp_dirs, monkeypatch
):
    """Stop-loss holding issue gets exit-triggered + result-stoploss-hit."""
    monkeypatch.setenv("MONITOR_RUN_ID", "12345")
    monitor_dir, report_dir = tmp_dirs
    exit_checker_mod._MONITOR_DIR = str(monitor_dir)
    exit_checker_mod._REPORT_DIR = str(report_dir)

    _write_monitor_report(
        monitor_dir,
        [
            {
                "issue_number": 42,
                "ticker": "2330",
                "setup_type": "a",
                "entry_price": 100.0,
                "close": 90.0,
                "pnl_pct": -10.0,
                "exit_signals": [],
                "partial_signals": [],
                "stoploss_triggered": True,
                "stopprofit_reminder": False,
            }
        ],
    )
    mock_gh.side_effect = _make_fake_gh(has_holding=True)

    assert _run_exit_checker() == 0

    report_path = report_dir / "exit_report_20260728.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["exit_triggered_count"] == 1
    assert report["processed_count"] == 1

    calls = [call.args[0] for call in mock_gh.call_args_list]
    edit_calls = [c for c in calls if c[:2] == ["issue", "edit"]]
    assert any(
        c == ["issue", "edit", "42", "--add-label", "exit-triggered", "--remove-label", "holding"]
        for c in edit_calls
    )
    assert any(
        c == ["issue", "edit", "42", "--add-label", "result-stoploss-hit"]
        for c in edit_calls
    )


@patch.object(exit_checker_mod, "_run_gh")
@patch.object(exit_checker_mod, "_today_taiwan_compact", return_value="20260728")
@patch.object(exit_checker_mod, "_today_taiwan_str", return_value="2026-07-28")
def test_exit_checker_signal_exit_adds_exit_triggered_only(
    mock_today, mock_compact, mock_gh, tmp_dirs, monkeypatch
):
    """Signal exit adds exit-triggered but not result-stoploss-hit."""
    monkeypatch.setenv("MONITOR_RUN_ID", "12345")
    monitor_dir, report_dir = tmp_dirs
    exit_checker_mod._MONITOR_DIR = str(monitor_dir)
    exit_checker_mod._REPORT_DIR = str(report_dir)

    _write_monitor_report(
        monitor_dir,
        [
            {
                "issue_number": 43,
                "ticker": "2317",
                "setup_type": "a",
                "entry_price": 100.0,
                "close": 95.0,
                "pnl_pct": -5.0,
                "exit_signals": ["E1 法人轉弱"],
                "partial_signals": [],
                "stoploss_triggered": False,
                "stopprofit_reminder": False,
            }
        ],
    )
    mock_gh.side_effect = _make_fake_gh(has_holding=True)

    assert _run_exit_checker() == 0

    report = json.loads((report_dir / "exit_report_20260728.json").read_text(encoding="utf-8"))
    assert report["exit_triggered_count"] == 1

    calls = [call.args[0] for call in mock_gh.call_args_list]
    edit_calls = [c for c in calls if c[:2] == ["issue", "edit"]]
    assert any(
        c == ["issue", "edit", "43", "--add-label", "exit-triggered", "--remove-label", "holding"]
        for c in edit_calls
    )
    assert not any(
        "result-stoploss-hit" in c for c in edit_calls
    )


@patch.object(exit_checker_mod, "_run_gh")
@patch.object(exit_checker_mod, "_today_taiwan_compact", return_value="20260728")
@patch.object(exit_checker_mod, "_today_taiwan_str", return_value="2026-07-28")
def test_exit_checker_no_exit_signals_does_not_edit(
    mock_today, mock_compact, mock_gh, tmp_dirs, monkeypatch
):
    """Holding issue without exit signals or stop loss triggers no edit."""
    monkeypatch.setenv("MONITOR_RUN_ID", "12345")
    monitor_dir, report_dir = tmp_dirs
    exit_checker_mod._MONITOR_DIR = str(monitor_dir)
    exit_checker_mod._REPORT_DIR = str(report_dir)

    _write_monitor_report(
        monitor_dir,
        [
            {
                "issue_number": 44,
                "ticker": "2454",
                "setup_type": "a",
                "entry_price": 100.0,
                "close": 101.0,
                "pnl_pct": 1.0,
                "exit_signals": [],
                "partial_signals": [],
                "stoploss_triggered": False,
                "stopprofit_reminder": False,
            }
        ],
    )
    mock_gh.side_effect = _make_fake_gh(has_holding=True)

    assert _run_exit_checker() == 0

    report = json.loads((report_dir / "exit_report_20260728.json").read_text(encoding="utf-8"))
    assert report["exit_triggered_count"] == 0
    assert report["processed_count"] == 1

    calls = [call.args[0] for call in mock_gh.call_args_list]
    edit_calls = [c for c in calls if c[:2] == ["issue", "edit"]]
    assert len(edit_calls) == 0


@patch.object(exit_checker_mod, "_run_gh")
@patch.object(exit_checker_mod, "_today_taiwan_compact", return_value="20260728")
@patch.object(exit_checker_mod, "_today_taiwan_str", return_value="2026-07-28")
def test_exit_checker_no_holding_issues_ends_cleanly(
    mock_today, mock_compact, mock_gh, tmp_dirs, monkeypatch
):
    """Empty holdings list produces a valid report with zero counts."""
    monkeypatch.setenv("MONITOR_RUN_ID", "12345")
    monitor_dir, report_dir = tmp_dirs
    exit_checker_mod._MONITOR_DIR = str(monitor_dir)
    exit_checker_mod._REPORT_DIR = str(report_dir)

    _write_monitor_report(monitor_dir, [])
    mock_gh.side_effect = _make_fake_gh(has_holding=False)

    assert _run_exit_checker() == 0

    report = json.loads((report_dir / "exit_report_20260728.json").read_text(encoding="utf-8"))
    assert report["processed_count"] == 0
    assert report["exit_triggered_count"] == 0
    assert report["exits"] == []

    calls = [call.args[0] for call in mock_gh.call_args_list]
    assert not any(c[:2] == ["issue", "edit"] for c in calls)


@patch.object(exit_checker_mod, "_run_gh")
@patch.object(exit_checker_mod, "_today_taiwan_compact", return_value="20260728")
@patch.object(exit_checker_mod, "_today_taiwan_str", return_value="2026-07-28")
def test_exit_checker_dry_run_no_api_call(
    mock_today, mock_compact, mock_gh, tmp_dirs, monkeypatch
):
    """Dry-run mode reads labels but never calls gh issue edit."""
    monkeypatch.setenv("MONITOR_RUN_ID", "12345")
    monitor_dir, report_dir = tmp_dirs
    exit_checker_mod._MONITOR_DIR = str(monitor_dir)
    exit_checker_mod._REPORT_DIR = str(report_dir)

    _write_monitor_report(
        monitor_dir,
        [
            {
                "issue_number": 42,
                "ticker": "2330",
                "setup_type": "a",
                "entry_price": 100.0,
                "close": 90.0,
                "pnl_pct": -10.0,
                "exit_signals": [],
                "partial_signals": [],
                "stoploss_triggered": True,
                "stopprofit_reminder": False,
            }
        ],
    )
    mock_gh.side_effect = _make_fake_gh(has_holding=True)

    assert _run_exit_checker(dry_run=True) == 0

    calls = [call.args[0] for call in mock_gh.call_args_list]
    assert not any(c[:2] == ["issue", "edit"] for c in calls)

    report = json.loads((report_dir / "exit_report_20260728.json").read_text(encoding="utf-8"))
    assert report["exit_triggered_count"] == 1
