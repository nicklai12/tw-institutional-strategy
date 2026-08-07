"""Exit Checker: apply exit labels based on Signal Monitor report."""

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


_REPORT_DIR = "data/exit-checker"
_MONITOR_DIR = "data/monitor"
_MONITOR_ARTIFACT_NAME = "monitor-report-{run_id}"


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _today_taiwan() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei"))


def _today_taiwan_str() -> str:
    return _today_taiwan().strftime("%Y-%m-%d")


def _today_taiwan_compact() -> str:
    return _today_taiwan().strftime("%Y%m%d")


def _download_monitor_artifact(run_id: str, dest_dir: str) -> bool:
    result = _run_gh(
        [
            "run",
            "download",
            run_id,
            "--name",
            _MONITOR_ARTIFACT_NAME.format(run_id=run_id),
            "--dir",
            dest_dir,
        ]
    )
    if result.returncode != 0:
        print(f"ERROR: 無法下載 monitor artifact: {result.stderr.strip()}")
        return False
    return True


def _find_monitor_report(dest_dir: str) -> str | None:
    pattern = os.path.join(dest_dir, "monitor_report_*.json")
    paths = glob.glob(pattern)
    if not paths:
        # artifact may preserve the uploaded directory prefix
        pattern = os.path.join(dest_dir, "**", "monitor_report_*.json")
        paths = glob.glob(pattern, recursive=True)
    if not paths:
        return None
    return paths[0]


def _load_report(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: 無法讀取 monitor report {path}: {exc}")
        return None


def _issue_has_holding_label(number: int) -> bool:
    result = _run_gh(
        ["issue", "view", str(number), "--json", "labels"]
    )
    if result.returncode != 0:
        print(
            f"WARNING: 無法讀取 Issue #{number} 的 Labels: {result.stderr.strip()}"
        )
        return False
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    labels = data.get("labels", []) or []
    return any(lbl.get("name") == "holding" for lbl in labels)


def _determine_exit_reason(exit_signals: list[str], stoploss_triggered: bool) -> str:
    if stoploss_triggered:
        return "stop_loss"
    if any("E3 時間停利" in signal for signal in exit_signals):
        return "time_exit"
    return "signal_exit"


def _apply_exit(
    number: int,
    ticker: str,
    exit_reason: str,
    stoploss_triggered: bool,
    dry_run: bool,
) -> dict[str, Any] | None:
    labels_added = ["exit-triggered"]
    labels_removed = ["holding"]

    if dry_run:
        print(
            f"[DRY-RUN] Issue #{number} ({ticker}): "
            f"add {labels_added}, remove {labels_removed}"
        )
        if stoploss_triggered:
            print(f"[DRY-RUN] Issue #{number}: add result-stoploss-hit")
        return {
            "issue_number": number,
            "ticker": ticker,
            "exit_reason": exit_reason,
            "stoploss_triggered": stoploss_triggered,
            "labels_added": labels_added.copy(),
            "labels_removed": labels_removed.copy(),
        }

    result = _run_gh(
        [
            "issue",
            "edit",
            str(number),
            "--add-label",
            "exit-triggered",
            "--remove-label",
            "holding",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法更新 Issue #{number}: {result.stderr.strip()}")
        return None

    if stoploss_triggered:
        result = _run_gh(
            ["issue", "edit", str(number), "--add-label", "result-stoploss-hit"]
        )
        if result.returncode != 0:
            print(
                f"WARNING: 無法加上 result-stoploss-hit 到 Issue #{number}: "
                f"{result.stderr.strip()}"
            )
        else:
            labels_added.append("result-stoploss-hit")

    return {
        "issue_number": number,
        "ticker": ticker,
        "exit_reason": exit_reason,
        "stoploss_triggered": stoploss_triggered,
        "labels_added": labels_added,
        "labels_removed": labels_removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply exit labels from monitor report")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只印出將要執行的操作，不實際呼叫 gh issue edit",
    )
    args = parser.parse_args()

    monitor_run_id = os.environ.get("MONITOR_RUN_ID")
    if not monitor_run_id:
        print("ERROR: 缺少環境變數 MONITOR_RUN_ID")
        return 1

    if not _download_monitor_artifact(monitor_run_id, _MONITOR_DIR):
        return 1

    report_path = _find_monitor_report(_MONITOR_DIR)
    if report_path is None:
        print("ERROR: 找不到 monitor_report_YYYYMMDD.json")
        return 1

    report = _load_report(report_path)
    if report is None:
        return 1

    holdings = report.get("holdings", []) or []
    exits: list[dict[str, Any]] = []
    processed_count = 0

    for holding in holdings:
        number = holding.get("issue_number")
        ticker = holding.get("ticker", "")
        exit_signals = holding.get("exit_signals", []) or []
        stoploss_triggered = bool(holding.get("stoploss_triggered", False))

        if not isinstance(number, int):
            print(f"WARNING: 跳過缺少 issue_number 的 holding: {holding}")
            continue

        if not _issue_has_holding_label(number):
            print(f"INFO: Issue #{number} 沒有 holding Label，跳過")
            continue

        processed_count += 1

        if not exit_signals and not stoploss_triggered:
            continue

        exit_reason = _determine_exit_reason(exit_signals, stoploss_triggered)
        exit_record = _apply_exit(
            number=number,
            ticker=ticker,
            exit_reason=exit_reason,
            stoploss_triggered=stoploss_triggered,
            dry_run=args.dry_run,
        )
        if exit_record is not None:
            exits.append(exit_record)

    exit_report = {
        "date": _today_taiwan_str(),
        "source_monitor_run_id": monitor_run_id,
        "processed_count": processed_count,
        "exit_triggered_count": len(exits),
        "exits": exits,
    }

    os.makedirs(_REPORT_DIR, exist_ok=True)
    output_path = os.path.join(_REPORT_DIR, f"exit_report_{_today_taiwan_compact()}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(exit_report, f, ensure_ascii=False, indent=2)

    print(f"OK: Exit report written to {output_path}")
    print(
        f"processed={processed_count}, exit_triggered={len(exits)}, dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
