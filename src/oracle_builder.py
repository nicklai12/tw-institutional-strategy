"""Build oracle fixtures for Setup A by integrating fetcher and filter."""

import datetime
import json
import os
from collections import defaultdict
from typing import Any

from src.fetcher import fetch_institutional_all, fetch_price_and_ma, get_last_n_trading_dates
from src.filter import filter_setup_a


def _get_trading_window(end_date: str, n: int = 5) -> list[str]:
    """Return the last n trading dates ending on end_date, chronological order."""
    dates: list[str] = []
    current = datetime.datetime.strptime(end_date, "%Y%m%d").date()
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current -= datetime.timedelta(days=1)
    dates.reverse()
    return dates


def _format_date(date_str: str) -> str:
    """Convert 'YYYYMMDD' to 'YYYY-MM-DD'."""
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"


def build_oracle_for_date(date: str) -> tuple[dict, dict]:
    """Return (oracle_input, oracle_output) for one trading date.

    Steps:
        1. Fetch T86 institutional data for the 5 trading days ending on `date`.
        2. Sum foreign_net and trust_net per ticker over the 5-day window.
        3. Pre-filter to tickers with positive 5-day foreign and trust net,
           then fetch price/MA data for the target date.
        4. Skip tickers where fetch_price_and_ma returns None.
        5. Run filter_setup_a on the complete candidate list.

    Args:
        date: Trading date in 'YYYYMMDD' format.

    Returns:
        Tuple of (oracle_input, oracle_output) dicts.
    """
    window = _get_trading_window(date, n=5)

    aggregated: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"name": "", "foreign_net": 0.0, "trust_net": 0.0}
    )
    for d in window:
        daily = fetch_institutional_all(d)
        for stock in daily:
            ticker = stock["ticker"]
            aggregated[ticker]["name"] = stock["name"]
            aggregated[ticker]["foreign_net"] += stock["foreign_net"]
            aggregated[ticker]["trust_net"] += stock["trust_net"]

    candidates: list[dict] = []
    for ticker, info in aggregated.items():
        # Pre-filter: Setup A requires both foreign and trust to be positive.
        if info["foreign_net"] <= 0 or info["trust_net"] <= 0:
            continue
        price = fetch_price_and_ma(ticker, date)
        if price is None:
            print(f"  Skip {ticker}: no price/MA data")
            continue
        candidates.append(
            {
                "ticker": ticker,
                "name": info["name"],
                "foreign_5d_net": round(info["foreign_net"], 2),
                "trust_5d_net": round(info["trust_net"], 2),
                "close": price["close"],
                "ma20": price["ma20"],
                "ma20_direction": price["ma20_direction"],
                "avg_volume_20d": price["avg_volume_20d"],
            }
        )

    setup_a = filter_setup_a(candidates)
    formatted = _format_date(date)

    oracle_input = {
        "date": formatted,
        "source": "TWSE T86 + STOCK_DAY API",
        "stocks": candidates,
    }
    oracle_output = {
        "date": formatted,
        "setup_a_candidates": setup_a,
        "manually_verified_by": "PENDING",
        "verified_at": None,
    }
    return oracle_input, oracle_output


def build_all_oracles(n_days: int = 5, output_dir: str = "tests/fixtures") -> None:
    """Fetch the last n trading days and save oracle input/output JSON files.

    Creates output_dir if it does not exist.
    """
    os.makedirs(output_dir, exist_ok=True)
    dates = get_last_n_trading_dates(n_days)

    for date in dates:
        print(f"正在處理 {date}...")
        oracle_input, oracle_output = build_oracle_for_date(date)
        formatted = _format_date(date)
        with open(
            os.path.join(output_dir, f"{formatted}_input.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(oracle_input, f, ensure_ascii=False, indent=2)
        with open(
            os.path.join(output_dir, f"{formatted}_output.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(oracle_output, f, ensure_ascii=False, indent=2)
        print(
            f"  完成：{len(oracle_input['stocks'])} 筆候選，"
            f"Setup A: {len(oracle_output['setup_a_candidates'])} 筆"
        )


if __name__ == "__main__":
    build_all_oracles()
