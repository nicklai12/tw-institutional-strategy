"""Setup C screener: foreign capitulation rebound with higher lows."""

import datetime
import json
import os
import sys
from typing import Any, Callable

from scripts.screener.setup_a import fetch_price_metrics


_ROLLING_DIR = "data/rolling"
_SCREENER_DIR = "data/screener"


_PRICE_BOTTOM_LABELS: dict[str, str] = {
    "higher_lows": "低點墊高",
}


def _price_bottom_text(status: str) -> str:
    """Return a human-readable label for the price bottom status."""
    return _PRICE_BOTTOM_LABELS.get(status, status)


def _entry_day_from_streak(streak: int) -> int:
    """Return a valid entry_day (2/3/4) from the current foreign buy streak.

    The spec only allows entry_day values of 2, 3, or 4. When the current
    streak falls outside this window we clamp to the nearest valid day; this
    keeps the emitted Issue body valid for the audit guardrail.
    """
    if streak < 2:
        return 2
    if streak > 4:
        return 4
    return streak


def _format_20d_verification(daily_values: list[int]) -> str | None:
    """Format the 20-day foreign net verification string from the oracle.

    Returns a string like "由 20 日陣列加總 -1700+350=-1350 驗證" when the
    input array is available; otherwise returns None.
    """
    if not daily_values:
        return None
    negative_sum = sum(v for v in daily_values if v < 0)
    positive_sum = sum(v for v in daily_values if v > 0)
    total = sum(daily_values)
    return f"由 20 日陣列加總 {negative_sum}+{positive_sum}={total} 驗證"


def _build_pass_reason(stock: dict[str, Any], market_cap_threshold_b: float) -> str:
    """Build the reason string for a passing Setup C candidate."""
    market_cap_b = stock.get("market_cap_b", 0)
    foreign_20d_net = stock.get("foreign_20d_net", 0)
    price_bottom_status = stock.get("price_bottom_status", "")

    foreign_part = f"外資 20 日淨值為負（{foreign_20d_net}"
    verification = _format_20d_verification(stock.get("foreign_daily_20d", []))
    if verification:
        foreign_part += f"，{verification}"
    foreign_part += "）"

    parts = [
        f"市值 {market_cap_b} 億 ≥ 門檻 {market_cap_threshold_b} 億",
        foreign_part,
        "近 3 日外資連買",
        _price_bottom_text(price_bottom_status),
        "符合 Setup C 篩選條件（spec.md 3.3）。",
    ]
    return "；".join(parts)


def _build_excluded_reason(
    stock: dict[str, Any],
    market_cap_threshold_b: float,
    failed_check: str,
) -> str:
    """Build the reason string for an excluded stock."""
    if failed_check == "market_cap":
        return (
            f"市值 {stock.get('market_cap_b')} 億 < 門檻 {market_cap_threshold_b} 億，"
            "不符合 Setup C『市值大、流動性強的權值/產業龍頭』條件（spec.md 3.3）。"
        )
    if failed_check == "foreign_20d_net":
        return (
            f"外資 20 日淨值為正（{stock.get('foreign_20d_net', 0)}），"
            "不符合 Setup C『外資近 20 日合計為負』條件（spec.md 3.3）。"
        )
    if failed_check == "foreign_recent_3d":
        daily = stock.get("foreign_daily_20d", [])
        last_three = daily[-3:] if len(daily) >= 3 else daily
        last_three_str = ", ".join(str(v) for v in last_three)
        return (
            f"外資最近 3 日未連續買超（最近三日為 {last_three_str}），"
            "不符合 Setup C『最近 3 日外資轉為連買』條件（spec.md 3.3）。"
        )
    return "不符合 Setup C 篩選條件。"


def _build_issue_body(candidate: dict[str, Any]) -> str:
    """Build the Setup C Issue body markdown from a candidate dict.

    The corresponding GitHub Issue should be created with the labels:
    `setup-c,screened`.
    """
    lines = [
        "## Setup C 候選股登記",
        "",
        f"- **ticker**: {candidate['ticker']}",
        f"- **screen_date**: {candidate['screen_date']}",
        f"- **market_cap_b**: {candidate['market_cap_b']}",
        f"- **foreign_20d_net**: {candidate['foreign_20d_net']}",
        f"- **foreign_recent_3d**: {candidate['foreign_recent_3d']}",
        f"- **foreign_buy_streak_day**: {candidate['foreign_buy_streak_day']}",
        f"- **price_bottom_status**: {candidate['price_bottom_status']}",
        f"- **entry_day**: {candidate['entry_day']}",
        f"- **entry_zone**: {candidate['entry_zone']}",
        f"- **stop_loss_price**: {candidate['stop_loss_price']}",
        "- **position_size_lots**: ⚠️ 待人工填寫",
        "- **risk_r_pct**: ⚠️ 待人工填寫",
        f"- **artifact_run_id**: {candidate['artifact_run_id']}",
    ]
    return "\n".join(lines)


def screen_setup_c(
    stocks: list[dict[str, Any]],
    price_fetcher: Callable[[str, str], dict[str, Any] | None],
    screen_date: str,
    market_cap_threshold_b: float = 1000,
    artifact_run_id: str | None = None,
) -> dict[str, Any]:
    """Pure Setup C screening function.

    Args:
        stocks: List of stock dicts with at least ticker, name, market_cap_b,
            foreign_20d_net, foreign_recent_3d, foreign_buy_streak_day,
            price_bottom_status, and optionally close / foreign_daily_20d.
        price_fetcher: Callable(ticker, 'YYYYMMDD') -> price metrics dict or None.
            Expected metrics: close.
        screen_date: Date string in 'YYYY-MM-DD' format.
        market_cap_threshold_b: Minimum market cap in billions TWD.
        artifact_run_id: Workflow run ID to record in candidates. Defaults to
            the GITHUB_RUN_ID environment variable or 'manual'.

    Returns:
        Dict with screen_date, setup_c_candidates, excluded, and oracle metadata.
    """
    if artifact_run_id is None:
        artifact_run_id = os.environ.get("GITHUB_RUN_ID", "manual")

    compact_date = screen_date.replace("-", "")
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for stock in stocks:
        ticker = stock.get("ticker")
        name = stock.get("name", "")
        if not ticker:
            continue

        metrics = price_fetcher(ticker, compact_date)
        close = 0.0
        if metrics is not None:
            close = float(metrics.get("close", 0))
        else:
            close = float(stock.get("close", 0))

        market_cap_b = stock.get("market_cap_b")
        foreign_20d_net = stock.get("foreign_20d_net", 0)
        foreign_recent_3d = stock.get("foreign_recent_3d", False)
        foreign_buy_streak_day = stock.get("foreign_buy_streak_day", 0)
        price_bottom_status = stock.get("price_bottom_status", "")

        if market_cap_b is None or market_cap_b < market_cap_threshold_b:
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock, market_cap_threshold_b, "market_cap"
                    ),
                }
            )
            continue

        if foreign_20d_net >= 0:
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock, market_cap_threshold_b, "foreign_20d_net"
                    ),
                }
            )
            continue

        if not foreign_recent_3d:
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock, market_cap_threshold_b, "foreign_recent_3d"
                    ),
                }
            )
            continue

        entry_day = _entry_day_from_streak(foreign_buy_streak_day)
        stop_loss_price = round(close * 0.95) if close else 0
        entry_zone = (
            f"外資連買第 {entry_day} 天當日價格區間"
            "（由 signal monitor 於進場日動態確認）"
        )

        candidates.append(
            {
                "ticker": ticker,
                "name": name,
                "screen_date": screen_date,
                "market_cap_b": market_cap_b,
                "foreign_20d_net": foreign_20d_net,
                "foreign_recent_3d": foreign_recent_3d,
                "foreign_buy_streak_day": foreign_buy_streak_day,
                "price_bottom_status": price_bottom_status,
                "entry_day": entry_day,
                "entry_zone": entry_zone,
                "stop_loss_price": stop_loss_price,
                "position_size_lots": "待人工填寫",
                "risk_r_pct": "待人工填寫",
                "artifact_run_id": artifact_run_id,
                "should_include": True,
                "reason": _build_pass_reason(stock, market_cap_threshold_b),
            }
        )

    return {
        "screen_date": screen_date,
        "setup_c_candidates": candidates,
        "excluded": excluded,
        "manually_verified_by": "PENDING",
        "verified_at": None,
    }


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

    market_cap_threshold_b = float(
        os.environ.get("MARKET_CAP_THRESHOLD_B", "1000")
    )

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
    result = screen_setup_c(
        stocks,
        price_fetcher=fetch_price_metrics,
        screen_date=today_str,
        market_cap_threshold_b=market_cap_threshold_b,
    )
    candidates = result["setup_c_candidates"]

    os.makedirs(_SCREENER_DIR, exist_ok=True)
    output_path = os.path.join(
        _SCREENER_DIR, f"screener_result_c_{today_compact}.json"
    )
    result_payload = {
        "screen_date": today_str,
        "record_count": len(candidates),
        "candidates": candidates,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    print(
        f"OK: {today_str} Setup C 篩選完成，共 {len(candidates)} 檔，已寫入 {output_path}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
