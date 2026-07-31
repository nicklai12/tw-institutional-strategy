"""Fetch daily institutional trading data from TWSE and store as raw JSON."""

import argparse
import datetime
import json
import os
import sys
from typing import Any

import requests


_API_BASE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
_SELECT_TYPE = "ALLBUT0999"
_RAW_OUTPUT_DIR = "data/raw"
_MIN_RECORD_COUNT = 100
_API_TIMEOUT_SECONDS = 10

# Field names observed in the TWSE T86 response for selectType=ALLBUT0999.
_FIELD_TICKER = "證券代號"
_FIELD_NAME = "證券名稱"
_FIELD_FOREIGN_BUY = "外陸資買進股數(不含外資自營商)"
_FIELD_FOREIGN_SELL = "外陸資賣出股數(不含外資自營商)"
_FIELD_TRUST_BUY = "投信買進股數"
_FIELD_TRUST_SELL = "投信賣出股數"
_FIELD_DEALER_NET = "自營商買賣超股數"
_REQUIRED_FIELDS = [
    _FIELD_TICKER,
    _FIELD_NAME,
    _FIELD_FOREIGN_BUY,
    _FIELD_FOREIGN_SELL,
    _FIELD_TRUST_BUY,
    _FIELD_TRUST_SELL,
    _FIELD_DEALER_NET,
]


def _share_string_to_lot(share_str: str) -> int:
    """Convert a TWSE share-count string to integer lots (張), rounding halves."""
    cleaned = str(share_str).replace(",", "").strip()
    if not cleaned:
        return 0
    return round(float(cleaned) / 1000)


def parse_institutional_response(
    response_data: dict[str, Any],
    fetch_date: str,
    source_url: str,
    fetch_timestamp: str | None = None,
) -> dict[str, Any]:
    """Parse a TWSE T86 JSON response into the canonical raw data schema.

    Args:
        response_data: Parsed JSON dict from TWSE T86.
        fetch_date: Trading date in 'YYYY-MM-DD' format.
        source_url: Full request URL used to fetch the data.
        fetch_timestamp: ISO8601 timestamp string. Defaults to now.

    Returns:
        Dict matching the raw institutional data schema.
    """
    if fetch_timestamp is None:
        fetch_timestamp = datetime.datetime.now().isoformat()

    fields: list[str] = response_data.get("fields", [])
    rows: list[list] = response_data.get("data", [])

    indices = {}
    for name in _REQUIRED_FIELDS:
        if name not in fields:
            raise ValueError(f"Missing required field in TWSE response: {name}")
        indices[name] = fields.index(name)

    data: list[dict[str, Any]] = []
    for row in rows:
        if len(row) <= max(indices.values()):
            continue

        try:
            foreign_buy = _share_string_to_lot(row[indices[_FIELD_FOREIGN_BUY]])
            foreign_sell = _share_string_to_lot(row[indices[_FIELD_FOREIGN_SELL]])
            trust_buy = _share_string_to_lot(row[indices[_FIELD_TRUST_BUY]])
            trust_sell = _share_string_to_lot(row[indices[_FIELD_TRUST_SELL]])
            dealer_net = _share_string_to_lot(row[indices[_FIELD_DEALER_NET]])
        except (ValueError, TypeError):
            continue

        data.append(
            {
                "ticker": str(row[indices[_FIELD_TICKER]]).strip(),
                "name": str(row[indices[_FIELD_NAME]]).strip(),
                "foreign_buy": foreign_buy,
                "foreign_sell": foreign_sell,
                "foreign_net": foreign_buy - foreign_sell,
                "trust_buy": trust_buy,
                "trust_sell": trust_sell,
                "trust_net": trust_buy - trust_sell,
                "dealer_net": dealer_net,
            }
        )

    return {
        "fetch_date": fetch_date,
        "fetch_timestamp": fetch_timestamp,
        "source_url": source_url,
        "record_count": len(data),
        "data": data,
    }


def is_trading_day(date: datetime.date) -> bool:
    """Return True if the date is a weekday.

    Public holidays are not modeled; this is the same simplification used by
    the existing project fetcher.
    """
    return date.weekday() < 5


def _format_date(date: datetime.date) -> str:
    return date.strftime("%Y-%m-%d")


def _compact_date(date: datetime.date) -> str:
    return date.strftime("%Y%m%d")


def _build_source_url(compact_date: str) -> str:
    return f"{_API_BASE_URL}?date={compact_date}&selectType={_SELECT_TYPE}"


def fetch_institutional(date: datetime.date) -> dict[str, Any]:
    """Fetch institutional data for a single trading date.

    Performs guardrail checks and raises RuntimeError on failure.
    """
    if not is_trading_day(date):
        raise RuntimeError("SKIP")

    compact = _compact_date(date)
    source_url = _build_source_url(compact)

    try:
        response = requests.get(source_url, timeout=_API_TIMEOUT_SECONDS)
        response.raise_for_status()
        response_data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("API_CONNECTION_FAILED") from exc
    except ValueError as exc:
        raise RuntimeError("API_INVALID_JSON") from exc

    if not isinstance(response_data, dict):
        raise RuntimeError("API_INVALID_RESPONSE")

    fetch_date = _format_date(date)
    fetch_timestamp = datetime.datetime.now().isoformat()
    parsed = parse_institutional_response(
        response_data, fetch_date, source_url, fetch_timestamp
    )

    if parsed["record_count"] <= _MIN_RECORD_COUNT:
        raise RuntimeError("TOO_FEW_RECORDS")

    return parsed


def _write_raw_file(date: datetime.date, result: dict[str, Any]) -> str:
    """Write a single parsed result to data/raw/YYYYMMDD.json."""
    os.makedirs(_RAW_OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(_RAW_OUTPUT_DIR, f"{_compact_date(date)}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return output_path


def _backfill_trading_days(backfill_days: int, today: datetime.date) -> int:
    """Fetch up to backfill_days recent trading days, skipping existing files.

    Non-trading days are skipped. Days that fail the TWSE API are logged as
    warnings and skipped so the loop can continue. Returns shell exit code 0.
    """
    os.makedirs(_RAW_OUTPUT_DIR, exist_ok=True)

    success_count = 0
    skipped_count = 0
    candidate = today

    while success_count + skipped_count < backfill_days:
        if not is_trading_day(candidate):
            candidate -= datetime.timedelta(days=1)
            continue

        compact = _compact_date(candidate)
        output_path = os.path.join(_RAW_OUTPUT_DIR, f"{compact}.json")

        if os.path.exists(output_path):
            print(f"SKIP: {compact} 已存在")
            skipped_count += 1
            candidate -= datetime.timedelta(days=1)
            continue

        try:
            result = fetch_institutional(candidate)
        except RuntimeError as exc:
            print(f"WARNING: {compact} 抓取失敗 ({exc})，跳過")
            candidate -= datetime.timedelta(days=1)
            continue

        output_path = _write_raw_file(candidate, result)
        print(
            f"OK: {result['fetch_date']} 共 {result['record_count']} 筆，"
            f"已寫入 {output_path}"
        )
        success_count += 1
        candidate -= datetime.timedelta(days=1)

    print(
        f"OK: backfill 完成，成功寫入 {success_count} 個交易日，"
        f"跳過已存在 {skipped_count} 個"
    )
    return 0


def main(backfill_days: int = 0) -> int:
    """Entry point. Returns shell exit code."""
    today = datetime.date.today()

    if backfill_days > 0:
        return _backfill_trading_days(backfill_days, today)

    if not is_trading_day(today):
        print("SKIP: 今日非交易日")
        return 0

    try:
        result = fetch_institutional(today)
    except RuntimeError as exc:
        code = str(exc)
        if code == "SKIP":
            print("SKIP: 今日非交易日")
            return 0
        if code == "API_CONNECTION_FAILED":
            print("ERROR: API 連線失敗")
        elif code == "TOO_FEW_RECORDS":
            print("ERROR: 數據異常，記錄數過少")
        else:
            print(f"ERROR: {code}")
        return 1

    output_path = _write_raw_file(today, result)
    print(
        f"OK: {result['fetch_date']} 共 {result['record_count']} 筆，"
        f"已寫入 {output_path}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch institutional trading data from TWSE."
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=0,
        help="Number of recent trading days to backfill (default: 0).",
    )
    args = parser.parse_args()
    sys.exit(main(args.backfill_days))
