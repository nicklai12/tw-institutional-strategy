"""Manager Loop: daily risk guardrails for screened issues."""

import json
import os
import subprocess
import sys
from datetime import date
from typing import Any

import requests


_REPORT_DIR = "data/manager"
_INDEX_API_URL = "https://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST"
_HOLDING_CAP = 6
_MARKET_DROP_THRESHOLD_PCT = -2.0


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _today_compact() -> str:
    return date.today().strftime("%Y%m%d")


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _fetch_json(url: str, timeout: int = 15) -> Any | None:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_market_drop_pct(today_str: str) -> float | None:
    """Return the TAIEX daily change percentage for today, or None if unavailable."""
    data = _fetch_json(_INDEX_API_URL)
    if not isinstance(data, list):
        return None

    closes: list[tuple[str, float]] = []
    for item in data:
        try:
            roc = item["Date"]
            year = int(roc[:3]) + 1911
            month = int(roc[3:5])
            day = int(roc[5:7])
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            close = float(item["ClosingIndex"])
            closes.append((date_str, close))
        except (KeyError, ValueError, TypeError):
            continue

    closes.sort(key=lambda x: x[0])

    for i, (d, close) in enumerate(closes):
        if d == today_str:
            if i == 0:
                return 0.0
            prev_close = closes[i - 1][1]
            if prev_close == 0:
                return 0.0
            return round((close - prev_close) / prev_close * 100, 2)

    return None


def list_issues_by_label(label: str) -> list[dict[str, Any]]:
    """List open issues with the given label."""
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            label,
            "--json",
            "number,labels,title",
            "--limit",
            "1000",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法讀取 {label} Issues: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def has_label(issue: dict[str, Any], label: str) -> bool:
    labels = issue.get("labels", []) or []
    return any(lbl.get("name") == label for lbl in labels)


def add_label_to_issue(number: int, label: str) -> bool:
    """Add a label to an issue, skipping if it is already present."""
    result = _run_gh(
        ["issue", "edit", str(number), "--add-label", label]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法對 Issue #{number} 加上 {label}: {result.stderr.strip()}")
        return False
    return True


def add_comment_to_issue(number: int, body: str) -> bool:
    result = _run_gh(
        ["issue", "comment", str(number), "--body", body]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法對 Issue #{number} 留言: {result.stderr.strip()}")
        return False
    return True


def _build_market_warning_comment(drop_pct: float) -> str:
    return (
        "⚠️ Manager: 大盤急跌 >2%，請人工確認是否進場\n\n"
        f"- 加權指數今日漲跌：{drop_pct:.2f}%"
    )


def _build_guardrail_comment(current_holding_count: int) -> str:
    return (
        "🚫 Guardrail: 持倉已達上限(6)，請先出場部分標的\n\n"
        f"- 目前持有中 Issue 數量：{current_holding_count}"
    )


def main() -> int:
    today_str = _today_str()
    today_compact = _today_compact()

    screened_issues = list_issues_by_label("screened")
    screened_issues = [
        issue for issue in screened_issues if not has_label(issue, "human-review")
    ]

    holding_issues = list_issues_by_label("holding")
    holding_count = len(holding_issues)

    market_drop_pct = fetch_market_drop_pct(today_str)
    market_warning_triggered = (
        market_drop_pct is not None and market_drop_pct < _MARKET_DROP_THRESHOLD_PCT
    )
    holding_cap_triggered = holding_count >= _HOLDING_CAP

    processed = 0
    for issue in screened_issues:
        number = issue["number"]
        processed += 1

        if market_warning_triggered and not has_label(issue, "human-review"):
            add_label_to_issue(number, "human-review")
            add_comment_to_issue(number, _build_market_warning_comment(market_drop_pct))
            print(f"OK: Issue #{number} 標記 human-review（大盤急跌）")

        if holding_cap_triggered and not has_label(issue, "guardrail-blocked"):
            add_label_to_issue(number, "guardrail-blocked")
            add_comment_to_issue(number, _build_guardrail_comment(holding_count))
            print(f"OK: Issue #{number} 標記 guardrail-blocked（持倉上限）")

    report = {
        "date": today_str,
        "market_drop_pct": market_drop_pct,
        "market_warning_triggered": market_warning_triggered,
        "current_holding_count": holding_count,
        "holding_cap_triggered": holding_cap_triggered,
        "processed_issue_count": processed,
    }

    os.makedirs(_REPORT_DIR, exist_ok=True)
    report_path = os.path.join(_REPORT_DIR, f"manager_report_{today_compact}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"OK: Manager report written to {report_path}")
    print(
        f"market_drop_pct={market_drop_pct}, holding_count={holding_count}, "
        f"processed={processed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
