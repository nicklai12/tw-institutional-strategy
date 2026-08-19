"""Fetch daily institutional trading data from TWSE and store as raw JSON."""

import argparse
import datetime
import glob
import json
import os
import sys
import time
from typing import Any

import requests


_API_BASE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
_SELECT_TYPE = "ALLBUT0999"
_RAW_OUTPUT_DIR = "data/raw"
_MIN_RECORD_COUNT = 100
_API_TIMEOUT_SECONDS = 10
_MAX_RAW_AGE_DAYS = 7

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE_SECONDS = 5
_RETRY_BACKOFF_MULTIPLIER = 2

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


def _fetch_with_retry(url: str) -> dict[str, Any]:
    """Fetch TWSE JSON with retries, backoff and browser-like headers.

    Retries on connection/timeout errors, non-OK HTTP status, malformed JSON,
    and TWSE ``stat != "OK"``. Preserves the original RuntimeError codes used
    by callers.
    """
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.get(
                url, headers=_REQUEST_HEADERS, timeout=_API_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            response_data = response.json()
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            response_snippet = ""
            if exc.response is not None:
                try:
                    response_snippet = exc.response.text[:200]
                except Exception:
                    pass
            print(
                f"WARN: API request attempt {attempt}/{_MAX_RETRIES} for {url} "
                f"failed: {exc} (status={status_code}) {response_snippet!r}"
            )
            last_exc = exc
        except ValueError as exc:
            print(
                f"WARN: API request attempt {attempt}/{_MAX_RETRIES} for {url} "
                f"returned invalid JSON: {exc}"
            )
            last_exc = exc
        else:
            if not isinstance(response_data, dict):
                print(
                    f"WARN: API request attempt {attempt}/{_MAX_RETRIES} for {url} "
                    f"returned non-dict JSON: {type(response_data).__name__}"
                )
                last_exc = ValueError("API_INVALID_RESPONSE")
            elif response_data.get("stat") != "OK":
                stat = response_data.get("stat")
                snippet = json.dumps(response_data, ensure_ascii=False)[:200]
                print(
                    f"WARN: API request attempt {attempt}/{_MAX_RETRIES} for {url} "
                    f"returned stat={stat!r} (snip: {snippet})"
                )
                last_exc = RuntimeError("STAT_NOT_OK")
            else:
                return response_data

        if attempt < _MAX_RETRIES:
            sleep_seconds = _RETRY_BACKOFF_BASE_SECONDS * (
                _RETRY_BACKOFF_MULTIPLIER ** (attempt - 1)
            )
            print(f"WARN: retrying in {sleep_seconds}s ...")
            time.sleep(sleep_seconds)

    if isinstance(last_exc, ValueError):
        raise RuntimeError("API_INVALID_JSON") from last_exc
    if isinstance(last_exc, RuntimeError) and str(last_exc) == "STAT_NOT_OK":
        raise RuntimeError("STAT_NOT_OK") from last_exc
    raise RuntimeError("API_CONNECTION_FAILED") from last_exc


def fetch_institutional(date: datetime.date) -> dict[str, Any]:
    """Fetch institutional data for a single trading date.

    Performs guardrail checks and raises RuntimeError on failure.
    """
    if not is_trading_day(date):
        raise RuntimeError("SKIP")

    compact = _compact_date(date)
    source_url = _build_source_url(compact)

    response_data = _fetch_with_retry(source_url)

    fetch_date = _format_date(date)
    fetch_timestamp = datetime.datetime.now().isoformat()
    try:
        parsed = parse_institutional_response(
            response_data, fetch_date, source_url, fetch_timestamp
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

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


def _latest_raw_date(raw_dir: str) -> datetime.date | None:
    """Return the latest trading date found in raw_dir/*.json, or None."""
    latest: datetime.date | None = None
    for path in glob.glob(os.path.join(raw_dir, "*.json")):
        basename = os.path.basename(path)
        date_part = basename.replace(".json", "")
        if len(date_part) != 8 or not date_part.isdigit():
            continue
        d = datetime.datetime.strptime(date_part, "%Y%m%d").date()
        if latest is None or d > latest:
            latest = d
    return latest


def _ensure_data_fresh(today: datetime.date, raw_dir: str) -> bool:
    """Fail if the latest raw file is older than _MAX_RAW_AGE_DAYS from today."""
    latest = _latest_raw_date(raw_dir)
    if latest is None:
        print("ERROR: 找不到任何原始資料")
        return False
    age_days = (today - latest).days
    if age_days > _MAX_RAW_AGE_DAYS:
        print(
            f"ERROR: 資料過舊，最新原始日期為 {latest.isoformat()}（距今 {age_days} 天，"
            f"超過 {_MAX_RAW_AGE_DAYS} 天）"
        )
        return False
    return True


def _backfill_trading_days(backfill_days: int, today: datetime.date) -> int:
    """Fetch up to backfill_days recent trading days, skipping existing files.

    Non-trading days and dates with no usable TWSE data are skipped and logged
    as warnings so the loop can continue. The workflow is not failed because of
    a missing historical date. Returns shell exit code 0.
    """
    os.makedirs(_RAW_OUTPUT_DIR, exist_ok=True)

    success_count = 0
    skipped_count = 0
    skipped_invalid_count = 0
    attempted_count = 0
    filled_count = 0
    candidate = today
    # Allow extra headroom for API failures / holidays without looping forever.
    max_attempts = backfill_days * 3

    while filled_count < backfill_days and attempted_count < max_attempts:
        if not is_trading_day(candidate):
            candidate -= datetime.timedelta(days=1)
            continue

        attempted_count += 1
        compact = _compact_date(candidate)
        output_path = os.path.join(_RAW_OUTPUT_DIR, f"{compact}.json")

        if os.path.exists(output_path):
            print(f"SKIP: {compact} 已存在")
            skipped_count += 1
            filled_count += 1
            candidate -= datetime.timedelta(days=1)
            continue

        try:
            result = fetch_institutional(candidate)
        except RuntimeError as exc:
            fetch_date = _format_date(candidate)
            reason = str(exc)
            print(f"SKIP: {fetch_date} TWSE 回傳無效資料（{reason}），跳過此日")
            skipped_invalid_count += 1
            candidate -= datetime.timedelta(days=1)
            continue

        output_path = _write_raw_file(candidate, result)
        print(
            f"OK: {result['fetch_date']} 共 {result['record_count']} 筆，"
            f"已寫入 {output_path}"
        )
        success_count += 1
        filled_count += 1
        candidate -= datetime.timedelta(days=1)

    print(
        f"OK: backfill 完成，成功寫入 {success_count} 個交易日，"
        f"跳過已存在 {skipped_count} 個，無資料 {skipped_invalid_count} 個"
    )
    return 0


def main(backfill_days: int = 0) -> int:
    """Entry point. Returns shell exit code."""
    today = datetime.date.today()

    if backfill_days > 0:
        rc = _backfill_trading_days(backfill_days, today)
        if rc != 0:
            return rc
        if not _ensure_data_fresh(today, _RAW_OUTPUT_DIR):
            return 1
        return 0

    if not is_trading_day(today):
        print("SKIP: 今日非交易日")
        if not _ensure_data_fresh(today, _RAW_OUTPUT_DIR):
            return 1
        return 0

    try:
        result = fetch_institutional(today)
    except RuntimeError as exc:
        code = str(exc)
        detail = f" ({exc.__cause__})" if exc.__cause__ is not None else ""
        if code == "SKIP":
            print("SKIP: 今日非交易日")
            return 0
        if code == "API_CONNECTION_FAILED":
            print(f"ERROR: API 連線失敗{detail}")
        elif code == "STAT_NOT_OK":
            print("ERROR: TWSE 資料尚未就緒（stat 不為 OK）")
        elif code == "TOO_FEW_RECORDS":
            print("ERROR: 數據異常，記錄數過少")
        elif code == "API_INVALID_JSON":
            print(f"ERROR: API 回傳非有效 JSON{detail}")
        else:
            print(f"ERROR: {code}{detail}")
        return 1

    output_path = _write_raw_file(today, result)
    print(
        f"OK: {result['fetch_date']} 共 {result['record_count']} 筆，"
        f"已寫入 {output_path}"
    )
    if not _ensure_data_fresh(today, _RAW_OUTPUT_DIR):
        return 1
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
