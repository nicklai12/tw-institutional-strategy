"""TWSE data fetcher for institutional trading and price/MA data."""

import datetime
import time
from typing import Any

import requests


_TWSE_T86_URL = "https://www.twse.com.tw/fund/T86"
_TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"


def _fetch_json(url: str) -> dict[str, Any] | None:
    """Fetch JSON from a TWSE endpoint, sleeping 0.5s after the request."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None
    finally:
        time.sleep(0.5)


def _to_roc_date(yyyymmdd: str) -> str:
    """Convert 'YYYYMMDD' to TWSE ROC date 'YYY/MM/DD'."""
    year = int(yyyymmdd[:4])
    roc_year = year - 1911
    return f"{roc_year}/{yyyymmdd[4:6]}/{yyyymmdd[6:]}"


def get_last_n_trading_dates(n: int) -> list[str]:
    """Return the last n trading dates in 'YYYYMMDD' format, most recent first.

    Only Saturdays and Sundays are skipped. Taiwan public holidays are not
    handled by this simplified implementation.
    """
    dates: list[str] = []
    current = datetime.date.today()
    while len(dates) < n:
        if current.weekday() < 5:  # Monday=0 ... Friday=4
            dates.append(current.strftime("%Y%m%d"))
        current -= datetime.timedelta(days=1)
    return dates


def fetch_institutional_all(date: str) -> list[dict]:
    """Fetch institutional net buy/sell data for all stocks from TWSE T86.

    Args:
        date: Date string in 'YYYYMMDD' format.

    Returns:
        A list of dicts with keys:
            - ticker: str
            - name: str
            - foreign_net: float (foreign total net, in 千股)
            - trust_net: float (trust net, in 千股)
        Returns an empty list if the market was closed or data is unavailable.
    """
    url = f"{_TWSE_T86_URL}?response=json&date={date}&selectType=ALL"
    data = _fetch_json(url)
    if data is None or data.get("stat") != "OK":
        return []

    fields = data.get("fields", [])
    rows = data.get("data", [])
    if not fields or not rows:
        return []

    def index_of(name: str) -> int:
        return fields.index(name) if name in fields else -1

    ticker_i = index_of("證券代號")
    name_i = index_of("證券名稱")
    foreign_i = index_of("外陸資買賣超股數(不含外資自營商)")
    foreign_prop_i = index_of("外資自營商買賣超股數")
    trust_i = index_of("投信買賣超股數")

    if ticker_i < 0 or name_i < 0 or foreign_i < 0 or trust_i < 0:
        return []

    required_indices = [ticker_i, name_i, foreign_i, trust_i]
    if foreign_prop_i >= 0:
        required_indices.append(foreign_prop_i)

    result: list[dict] = []
    for row in rows:
        if len(row) <= max(required_indices):
            continue
        try:
            foreign_net = int(row[foreign_i].replace(",", ""))
            if foreign_prop_i >= 0:
                foreign_net += int(row[foreign_prop_i].replace(",", ""))
            trust_net = int(row[trust_i].replace(",", ""))
            result.append(
                {
                    "ticker": str(row[ticker_i]).strip(),
                    "name": str(row[name_i]).strip(),
                    "foreign_net": round(foreign_net / 1000, 2),
                    "trust_net": round(trust_net / 1000, 2),
                }
            )
        except (ValueError, AttributeError, TypeError):
            continue
    return result


def _month_start_date(yyyymmdd: str) -> str:
    """Return the first day of the month for 'YYYYMMDD'."""
    return f"{yyyymmdd[:4]}{yyyymmdd[4:6]}01"


def _prev_month_date(yyyymmdd: str) -> str:
    """Return the first day of the previous month for 'YYYYMMDD'."""
    year = int(yyyymmdd[:4])
    month = int(yyyymmdd[4:6])
    if month == 1:
        year -= 1
        month = 12
    else:
        month -= 1
    return f"{year}{month:02d}01"


def _parse_stock_day_rows(rows: list[list], date_i: int, close_i: int, turnover_i: int) -> list[dict[str, Any]]:
    """Parse TWSE STOCK_DAY rows into a list of normalized dicts."""
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if len(row) <= max(date_i, close_i, turnover_i):
            continue
        try:
            parsed.append(
                {
                    "date": row[date_i],
                    "close": float(str(row[close_i]).replace(",", "")),
                    "turnover": float(str(row[turnover_i]).replace(",", "")),
                }
            )
        except (ValueError, AttributeError, TypeError):
            continue
    return parsed


def fetch_price_and_ma(ticker: str, date: str) -> dict | None:
    """Fetch daily K-lines around `date` and compute close / MA20 metrics.

    Args:
        ticker: Stock ticker, e.g. "2330".
        date: Date string in 'YYYYMMDD' format.

    Returns:
        A dict with keys:
            - close: float
            - ma20: float
            - ma20_direction: "rising" | "flat" | "falling"
            - avg_volume_20d: float (average daily turnover, in 千元)
        Returns None if the requested date is not found or if fewer than
        20 trading days (or 25, for the 5-day-ago MA20 direction) are
        available up to that date.

    Note:
        Both the month of `date` and the previous month are fetched from
        the TWSE STOCK_DAY API so that MA20 can be computed even early in
        the month.
    """
    target_roc = _to_roc_date(date)

    current_month = _month_start_date(date)
    previous_month = _prev_month_date(date)

    all_parsed: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for month_date in (previous_month, current_month):
        url = f"{_TWSE_STOCK_DAY_URL}?response=json&stockNo={ticker}&date={month_date}"
        data = _fetch_json(url)
        if data is None or data.get("stat") != "OK":
            continue

        fields = data.get("fields", [])
        rows = data.get("data", [])
        if not fields or not rows:
            continue

        date_i = fields.index("日期") if "日期" in fields else -1
        close_i = fields.index("收盤價") if "收盤價" in fields else -1
        turnover_i = fields.index("成交金額") if "成交金額" in fields else -1

        if date_i < 0 or close_i < 0 or turnover_i < 0:
            continue

        for item in _parse_stock_day_rows(rows, date_i, close_i, turnover_i):
            if item["date"] not in seen_dates:
                seen_dates.add(item["date"])
                all_parsed.append(item)

    all_parsed.sort(key=lambda x: x["date"])

    index = None
    for i, item in enumerate(all_parsed):
        if item["date"] == target_roc:
            index = i
            break

    if index is None or index < 24:
        return None

    window = all_parsed[index - 19 : index + 1]
    closes = [item["close"] for item in window]
    turnovers = [item["turnover"] for item in window]

    ma20_today = sum(closes) / len(closes)
    avg_volume_20d = sum(turnovers) / len(turnovers)

    prev_window = all_parsed[index - 24 : index - 4]
    prev_closes = [item["close"] for item in prev_window]
    ma20_5days_ago = sum(prev_closes) / len(prev_closes)

    diff = ma20_today - ma20_5days_ago
    pct = abs(diff) / ma20_5days_ago if ma20_5days_ago != 0 else 0.0
    if diff > 0 and pct > 0.001:
        direction = "rising"
    elif pct <= 0.001:
        direction = "flat"
    else:
        direction = "falling"

    return {
        "close": round(closes[-1], 2),
        "ma20": round(ma20_today, 2),
        "ma20_direction": direction,
        "avg_volume_20d": round(avg_volume_20d / 1000, 2),
    }
