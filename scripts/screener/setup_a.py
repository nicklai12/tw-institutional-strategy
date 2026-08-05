"""Setup A screener: dual institutional resonance with price confirmation."""

import datetime
import json
import os
import sys
import time
from collections import defaultdict
from typing import Any, Callable

import requests


_ROLLING_DIR = "data/rolling"
_SCREENER_DIR = "data/screener"
_PRICE_API_BASE = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"


def _to_roc_date(yyyymmdd: str) -> str:
    """Convert 'YYYYMMDD' to TWSE ROC date 'YYY/MM/DD'."""
    year = int(yyyymmdd[:4])
    roc_year = year - 1911
    return f"{roc_year}/{yyyymmdd[4:6]}/{yyyymmdd[6:]}"


def _month_start_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}{yyyymmdd[4:6]}01"


def _prev_month_date(yyyymmdd: str) -> str:
    year = int(yyyymmdd[:4])
    month = int(yyyymmdd[4:6])
    if month == 1:
        year -= 1
        month = 12
    else:
        month -= 1
    return f"{year}{month:02d}01"


def _fetch_json(url: str, timeout: int = 15) -> dict[str, Any] | None:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None
    finally:
        time.sleep(0.5)


def fetch_price_metrics(ticker: str, date: str) -> dict[str, Any] | None:
    """Fetch price history from TWSE and compute close, MA5, MA20, direction, avg volume.

    Args:
        ticker: Stock ticker, e.g. "2330".
        date: Date string in 'YYYYMMDD' format.

    Returns:
        Dict with keys: close, ma5, ma20, ma20_direction, avg_volume_20d.
        Returns None if the requested date is unavailable or insufficient history.
    """
    target_roc = _to_roc_date(date)
    current_month = _month_start_date(date)
    previous_month = _prev_month_date(date)

    parsed: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for month_date in (previous_month, current_month):
        url = f"{_PRICE_API_BASE}?stockNo={ticker}&date={month_date}"
        data = _fetch_json(url)
        if data is None or data.get("stat") != "OK":
            continue

        fields = data.get("fields", [])
        rows = data.get("data", [])
        if not fields or not rows:
            continue

        try:
            date_i = fields.index("日期")
            close_i = fields.index("收盤價")
            turnover_i = fields.index("成交金額")
        except ValueError:
            continue

        for row in rows:
            if len(row) <= max(date_i, close_i, turnover_i):
                continue
            try:
                item = {
                    "date": row[date_i],
                    "close": float(str(row[close_i]).replace(",", "")),
                    "turnover": float(str(row[turnover_i]).replace(",", "")),
                }
                if item["date"] not in seen_dates:
                    seen_dates.add(item["date"])
                    parsed.append(item)
            except (ValueError, TypeError):
                continue

    parsed.sort(key=lambda x: x["date"])

    index = None
    for i, item in enumerate(parsed):
        if item["date"] == target_roc:
            index = i
            break

    # Need 20 days for MA20 plus 5 more days to compare MA20 direction.
    if index is None or index < 24:
        return None

    window_20d = parsed[index - 19 : index + 1]
    closes_20d = [item["close"] for item in window_20d]
    turnovers_20d = [item["turnover"] for item in window_20d]
    ma20_today = sum(closes_20d) / len(closes_20d)
    ma5_today = sum(closes_20d[-5:]) / 5
    avg_volume_20d = sum(turnovers_20d) / len(turnovers_20d) / 1000  # 千元

    prev_window = parsed[index - 24 : index - 4]
    prev_closes = [item["close"] for item in prev_window]
    ma20_5days_ago = sum(prev_closes) / len(prev_closes)

    diff = ma20_today - ma20_5days_ago
    pct = abs(diff) / ma20_5days_ago if ma20_5days_ago != 0 else 0.0
    if diff > 0 and pct > 0.001:
        direction = "rising"
    elif diff > 0 and pct <= 0.001:
        direction = "flat_to_rising"
    elif diff < 0 and pct > 0.001:
        direction = "declining"
    elif diff < 0 and pct <= 0.001:
        direction = "flat_to_rising"
    else:
        direction = "flat"

    return {
        "close": round(closes_20d[-1], 2),
        "ma5": round(ma5_today, 2),
        "ma20": round(ma20_today, 2),
        "ma20_direction": direction,
        "avg_volume_20d": round(avg_volume_20d, 2),
    }


def _format_entry_zone(ma5: float, ma20: float) -> str:
    """Return 'lower-higher' zone between MA5 and MA20."""
    low = min(ma5, ma20)
    high = max(ma5, ma20)
    return f"{low:.2f}-{high:.2f}"


def screen_setup_a(
    stocks: list[dict[str, Any]],
    price_fetcher: Callable[[str, str], dict[str, Any] | None],
    screen_date: str,
    min_avg_volume_m: float = 500,
    max_candidates: int = 5,
    allowed_directions: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Pure Setup A screening function.

    Args:
        stocks: List of stock dicts with at least ticker, name, foreign_5d_net,
            trust_5d_net.
        price_fetcher: Callable(ticker, date) -> price metrics dict or None.
        screen_date: Date string in 'YYYY-MM-DD' format.
        min_avg_volume_m: Minimum average daily turnover in million TWD.
        max_candidates: Maximum number of candidates to return.
        allowed_directions: Set of accepted ma20_direction values.

    Returns:
        List of selected candidate dicts, sorted by total institutional net.
    """
    if allowed_directions is None:
        allowed_directions = {"rising", "flat_to_rising"}

    min_avg_volume_k = min_avg_volume_m * 1000  # 千元
    compact_date = screen_date.replace("-", "")

    # Step 1-2: filter by foreign resonance and trust resonance.
    passed_stage1: list[dict[str, Any]] = []
    for stock in stocks:
        foreign_net = stock.get("foreign_5d_net", 0)
        trust_net = stock.get("trust_5d_net", 0)

        if foreign_net <= 0 or trust_net <= 0:
            continue
        passed_stage1.append(stock)

    # Step 3-4: fetch price metrics and filter by liquidity + price structure.
    # avg_volume_20d comes from the price fetcher, not the upstream rolling JSON.
    passed_stage2: list[dict[str, Any]] = []
    for stock in passed_stage1:
        ticker = stock.get("ticker")
        if not ticker:
            continue

        metrics = price_fetcher(ticker, compact_date)
        if metrics is None:
            continue

        avg_volume = metrics.get("avg_volume_20d")
        close = metrics.get("close", 0)
        ma20 = metrics.get("ma20", float("inf"))
        direction = metrics.get("ma20_direction", "")

        if avg_volume is None or avg_volume <= min_avg_volume_k:
            continue
        if close <= ma20:
            continue
        if direction not in allowed_directions:
            continue

        passed_stage2.append({**stock, **metrics})

    # Step 5: sort by foreign_5d_net + trust_5d_net descending.
    passed_stage2.sort(
        key=lambda s: s.get("foreign_5d_net", 0) + s.get("trust_5d_net", 0),
        reverse=True,
    )

    # Step 6-7: limit and compute entry/stop-loss parameters.
    if len(passed_stage2) > max_candidates:
        print(
            f"WARNING: 候選數量 {len(passed_stage2)} 超過上限 {max_candidates}，只取前 {max_candidates} 檔"
        )
        passed_stage2 = passed_stage2[:max_candidates]

    result: list[dict[str, Any]] = []
    for stock in passed_stage2:
        close = stock.get("close", 0)
        ma5 = stock.get("ma5", 0)
        ma20 = stock.get("ma20", 0)
        result.append(
            {
                "ticker": stock.get("ticker"),
                "name": stock.get("name"),
                "screen_date": screen_date,
                "avg_volume_20d": stock.get("avg_volume_20d"),
                "avg_volume_20d_m": round(stock.get("avg_volume_20d", 0) / 1000, 2),
                "foreign_5d_net": stock.get("foreign_5d_net"),
                "trust_5d_net": stock.get("trust_5d_net"),
                "total_net_5d": round(
                    stock.get("foreign_5d_net", 0) + stock.get("trust_5d_net", 0), 2
                ),
                "close": close,
                "ma20": ma20,
                "ma20_direction": stock.get("ma20_direction"),
                "ma5": ma5,
                "entry_zone": _format_entry_zone(ma5, ma20),
                "stop_loss_price": round(close * 0.93),
                "position_size_lots": "待人工計算",
                "risk_r_pct": "待人工計算",
            }
        )

    return result


def load_rolling_json(date: datetime.date) -> dict[str, Any]:
    """Load the rolling data JSON for the given date."""
    compact = date.strftime("%Y%m%d")
    path = os.path.join(_ROLLING_DIR, f"{compact}_rolling.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 rolling 檔案: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _today_str() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


def _today_compact() -> str:
    return datetime.date.today().strftime("%Y%m%d")


def main() -> int:
    """Entry point. Returns shell exit code."""
    today = datetime.date.today()
    today_str = _today_str()
    today_compact = _today_compact()

    min_avg_volume_m = float(os.environ.get("MIN_AVG_VOLUME_M", "500"))
    max_candidates = int(os.environ.get("MAX_CANDIDATES_PER_RUN", "5"))

    try:
        rolling = load_rolling_json(today)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    rolling_date = rolling.get("fetch_date")
    if rolling_date != today_str:
        print(
            f"ERROR: rolling 日期不符（rolling={rolling_date}，今天={today_str}）"
        )
        return 1

    stocks = rolling.get("data", [])
    candidates = screen_setup_a(
        stocks,
        price_fetcher=fetch_price_metrics,
        screen_date=today_str,
        min_avg_volume_m=min_avg_volume_m,
        max_candidates=max_candidates,
    )

    os.makedirs(_SCREENER_DIR, exist_ok=True)
    output_path = os.path.join(
        _SCREENER_DIR, f"screener_result_a_{today_compact}.json"
    )
    result_payload = {
        "screen_date": today_str,
        "record_count": len(candidates),
        "candidates": candidates,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    print(
        f"OK: {today_str} 篩選完成，共 {len(candidates)} 檔，已寫入 {output_path}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
