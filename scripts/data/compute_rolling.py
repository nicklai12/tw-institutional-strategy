"""Compute rolling institutional metrics from recent raw data files."""

import glob
import json
import os
import sys
from collections import defaultdict
from typing import Any


_RAW_DIR = "data/raw"
_ROLLING_DIR = "data/rolling"
_MIN_RAW_FILES = 20


def _load_raw_files(raw_dir: str) -> list[tuple[str, dict[str, Any]]]:
    """Load all raw JSON files and return (YYYYMMDD, parsed_data) sorted by date."""
    loaded: list[tuple[str, dict[str, Any]]] = []
    for path in glob.glob(os.path.join(raw_dir, "*.json")):
        basename = os.path.basename(path)
        date_part = basename.replace(".json", "")
        if len(date_part) != 8 or not date_part.isdigit():
            continue
        with open(path, encoding="utf-8") as f:
            loaded.append((date_part, json.load(f)))
    loaded.sort(key=lambda x: x[0])
    return loaded


def _records_by_ticker(
    loaded: list[tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Map ticker -> {date -> record} across all loaded files."""
    by_ticker: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for date, payload in loaded:
        for record in payload.get("data", []):
            ticker = record.get("ticker")
            if not ticker:
                continue
            by_ticker[ticker][date] = record
    return dict(by_ticker)


def _sum_net(records: list[dict[str, Any]], net_field: str) -> int:
    return sum(r.get(net_field, 0) for r in records)


def _count_positive_days(records: list[dict[str, Any]], net_field: str) -> int:
    return sum(1 for r in records if r.get(net_field, 0) > 0)


def _all_positive(records: list[dict[str, Any]], net_field: str) -> bool:
    return all(r.get(net_field, 0) > 0 for r in records)


def _buy_streak_days(records: list[dict[str, Any]], net_field: str) -> int:
    """Count consecutive positive net values ending at the most recent record."""
    count = 0
    for r in reversed(records):
        if r.get(net_field, 0) > 0:
            count += 1
        else:
            break
    return count


def compute_rolling(raw_dir: str = _RAW_DIR) -> dict[str, Any]:
    """Compute rolling metrics from the most recent raw files.

    Returns:
        Canonical rolling output dict for the latest date.

    Notes:
        If fewer than 20 raw files are available, a warning is printed and
        metrics are computed using the available days (degraded mode).
    """
    loaded = _load_raw_files(raw_dir)
    if len(loaded) < _MIN_RAW_FILES:
        print(
            f"WARNING: 原始檔案不足：需要至少 {_MIN_RAW_FILES} 個交易日，"
            f"目前只有 {len(loaded)} 個，將以可用天數降級計算"
        )

    # Use the most recent 20 trading days (or fewer if not available).
    recent = loaded[-20:]
    recent_dates = [d for d, _ in recent]
    latest_date = recent_dates[-1]
    latest_payload = recent[-1][1]
    days_used = len(recent)

    by_ticker = _records_by_ticker(recent)

    # Build output records based on the latest day's tickers.
    rolling_data: list[dict[str, Any]] = []
    for record in latest_payload.get("data", []):
        ticker = record.get("ticker")
        if not ticker:
            continue

        history = by_ticker.get(ticker, {})

        def window_records(days: int) -> list[dict[str, Any]]:
            target_dates = recent_dates[-days:]
            return [history[d] for d in target_dates if d in history]

        rec_5d = window_records(5)
        rec_10d = window_records(10)
        rec_3d = window_records(3)

        rolling_record = {
            **record,
            "foreign_5d_net": _sum_net(rec_5d, "foreign_net"),
            "trust_5d_net": _sum_net(rec_5d, "trust_net"),
            "trust_10d_net": _sum_net(rec_10d, "trust_net"),
            "trust_10d_buy_days": _count_positive_days(rec_10d, "trust_net"),
            "foreign_10d_net": _sum_net(rec_10d, "foreign_net"),
            "foreign_20d_net": _sum_net(window_records(20), "foreign_net"),
            "foreign_recent_3d_all_buy": _all_positive(rec_3d, "foreign_net"),
            "foreign_buy_streak_day": _buy_streak_days(
                window_records(20), "foreign_net"
            ),
        }
        rolling_data.append(rolling_record)

    return {
        "fetch_date": latest_payload.get("fetch_date"),
        "fetch_timestamp": latest_payload.get("fetch_timestamp"),
        "source_url": latest_payload.get("source_url"),
        "record_count": len(rolling_data),
        "days_used": days_used,
        "data": rolling_data,
    }


def main() -> int:
    """Entry point. Returns shell exit code."""
    try:
        result = compute_rolling()
    except RuntimeError as exc:
        print(f"WARNING: {exc}")
        return 1

    os.makedirs(_ROLLING_DIR, exist_ok=True)
    latest_compact = result["fetch_date"].replace("-", "")
    output_path = os.path.join(_ROLLING_DIR, f"{latest_compact}_rolling.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(
        f"OK: {result['fetch_date']} 共 {result['record_count']} 筆，"
        f"使用 {result['days_used']} 個交易日，已寫入 {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
