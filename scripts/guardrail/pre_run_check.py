"""Guardrail: pre-run environment and data safety checks."""

import json
import os
import subprocess
import sys
from datetime import date, datetime
from typing import Any

import requests


_REPORT_DIR = "data/guardrail"
_TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
_ROLLING_DIR = "data/rolling"
_MAX_CANDIDATES_DEFAULT = 5


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _today_compact() -> str:
    return date.today().strftime("%Y%m%d")


def _set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _fetch_t86(date_compact: str, timeout: int = 10) -> dict[str, Any] | None:
    url = f"{_TWSE_T86_URL}?response=json&date={date_compact}&selectType=ALL"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def check_api_reachable(date_compact: str) -> bool:
    """Check 2: TWSE data API reachable."""
    data = _fetch_t86(date_compact, timeout=10)
    return data is not None


def check_trading_day(date_compact: str) -> bool:
    """Check 1: today is a Taiwan trading day."""
    data = _fetch_t86(date_compact, timeout=30)
    if data is None:
        return False
    if data.get("stat") != "OK":
        return False
    rows = data.get("data", [])
    return len(rows) > 0


def check_rolling_data(today_str: str) -> bool:
    """Check 3: rolling JSON exists and date matches today."""
    path = os.path.join(_ROLLING_DIR, f"{_today_compact()}_rolling.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("fetch_date") == today_str
    except (json.JSONDecodeError, OSError):
        return False


def check_holding_count() -> int:
    """Check 4: count open issues with holding label."""
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "holding",
            "--json",
            "number",
            "--limit",
            "1000",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法讀取 holding Issues: {result.stderr.strip()}")
        return 0
    try:
        issues = json.loads(result.stdout)
        return len(issues)
    except json.JSONDecodeError:
        return 0


def check_today_screener_done(today_str: str, max_candidates: int) -> bool:
    """Check 5: whether today's Setup A screener already produced max candidates."""
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "screened",
            "--search",
            f"created:{today_str}",
            "--json",
            "number,labels",
            "--limit",
            "100",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法查詢今日 screened Issues: {result.stderr.strip()}")
        return False
    try:
        issues = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False

    setup_a_count = sum(
        1
        for issue in issues
        if any(lbl.get("name") == "setup-a" for lbl in issue.get("labels", []))
    )
    return setup_a_count >= max_candidates


def _write_report(report: dict[str, Any], today_compact: str) -> None:
    os.makedirs(_REPORT_DIR, exist_ok=True)
    path = os.path.join(_REPORT_DIR, f"check_result_{today_compact}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main() -> int:
    today_str = _today_str()
    today_compact = _today_compact()

    skip_rolling = os.environ.get("SKIP_ROLLING_CHECK", "").lower() in ("1", "true", "yes")
    max_candidates = int(os.environ.get("MAX_CANDIDATES_PER_RUN", str(_MAX_CANDIDATES_DEFAULT)))

    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "is_trading_day": False,
        "api_reachable": False,
        "data_date_correct": False,
        "current_holding_count": 0,
        "today_screener_done": False,
        "overall_pass": False,
    }

    # Check 2 first so network failures are reported as fatal.
    api_reachable = check_api_reachable(today_compact)
    report["api_reachable"] = api_reachable
    if not api_reachable:
        print("GUARDRAIL FAIL: TWSE API unreachable")
        _write_report(report, today_compact)
        _set_output("passed", "false")
        return 1

    # Check 1
    is_trading_day = check_trading_day(today_compact)
    report["is_trading_day"] = is_trading_day
    if not is_trading_day:
        print("GUARDRAIL SKIP: non-trading day")
        _write_report(report, today_compact)
        _set_output("passed", "false")
        return 0

    # Check 3
    if skip_rolling:
        report["data_date_correct"] = True
    else:
        data_date_correct = check_rolling_data(today_str)
        report["data_date_correct"] = data_date_correct
        if not data_date_correct:
            print("GUARDRAIL FAIL: rolling data date mismatch")
            _write_report(report, today_compact)
            _set_output("passed", "false")
            return 1

    # Check 4
    holding_count = check_holding_count()
    report["current_holding_count"] = holding_count
    if holding_count >= 6:
        print(f"GUARDRAIL WARNING: holding count {holding_count} >= 6")

    # Check 5
    screener_done = check_today_screener_done(today_str, max_candidates)
    report["today_screener_done"] = screener_done
    if screener_done:
        print(f"GUARDRAIL SKIP: 今日 Setup A 已執行完畢")
        _write_report(report, today_compact)
        _set_output("passed", "false")
        return 0

    report["overall_pass"] = True
    _write_report(report, today_compact)
    _set_output("passed", "true")

    print("GUARDRAIL PASS: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
