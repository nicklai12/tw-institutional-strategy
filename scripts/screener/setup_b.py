"""Setup B screener: trust-led breakout with foreign-direction confirmation."""

import datetime
import json
import os
import sys
from typing import Any, Callable

from scripts.screener.setup_a import fetch_price_metrics


_ROLLING_DIR = "data/rolling"
_SCREENER_DIR = "data/screener"


def _avg_volume_m(metrics: dict[str, Any]) -> float | None:
    """Return avg daily turnover in million TWD from price metrics.

    Accepts either `avg_volume_20d_m` (already in million) or
    `avg_volume_20d` (in thousand TWD) as produced by Setup A's fetcher.
    """
    if "avg_volume_20d_m" in metrics:
        return float(metrics["avg_volume_20d_m"])
    avg_k = metrics.get("avg_volume_20d")
    if avg_k is None:
        return None
    return float(avg_k) / 1000


def _close_vs_ma20(metrics: dict[str, Any]) -> str:
    """Return 'above'/'below' based on close versus MA20."""
    if "close_vs_ma20" in metrics:
        return str(metrics["close_vs_ma20"])
    close = float(metrics.get("close", 0))
    ma20 = float(metrics.get("ma20", 0))
    return "above" if close > ma20 else "below"


def _compute_foreign_10d_direction(
    foreign_10d_net: float,
    close: float,
    avg_volume_m: float,
    threshold: float,
) -> str:
    """Compute Setup B foreign 10-day direction per spec.md 7.8."""
    if close == 0 or avg_volume_m is None:
        return "neutral"
    avg_daily_volume_lots = avg_volume_m * 1000 / close
    if avg_daily_volume_lots == 0:
        return "neutral"
    foreign_avg_daily_net = foreign_10d_net / 10
    ratio = foreign_avg_daily_net / avg_daily_volume_lots
    if ratio > threshold:
        return "buying"
    if ratio < -threshold:
        return "selling"
    return "neutral"


def _fmt_number(x: float) -> str:
    """Format a number without trailing '.0' when it is integral."""
    if isinstance(x, (int, float)) and float(x).is_integer():
        return str(int(x))
    return str(x)


def _rounded_volume_m(avg_volume_m: float | None) -> float | int | None:
    """Round volume and drop trailing '.0' for integral values."""
    if avg_volume_m is None:
        return None
    rounded = round(float(avg_volume_m), 2)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def _build_pass_reason(
    stock: dict[str, Any],
    metrics: dict[str, Any],
    direction: str,
    ratio: float,
    threshold: float,
) -> str:
    """Build the reason string for a passing Setup B candidate."""
    trust_buy_days = stock.get("trust_10d_buy_days")
    foreign_10d_net = stock.get("foreign_10d_net", 0)
    close = float(metrics.get("close", 0))
    avg_volume_m = _avg_volume_m(metrics)
    if avg_volume_m is None:
        avg_volume_m = 0.0

    parts = [
        f"投信 10 日淨買超為正且買超天數 {trust_buy_days} ≥ 7",
    ]

    if direction == "neutral":
        parts.append("外資 10 日方向為 neutral，非明顯大賣")
    else:
        avg_daily_volume_lots = avg_volume_m * 1000 / close
        foreign_avg_daily_net = foreign_10d_net / 10
        operator = ">" if direction == "buying" else "<"
        parts.append(
            f"外資 10 日方向為 {direction}（"
            f"ratio = ({_fmt_number(foreign_10d_net)}/10)/"
            f"({_fmt_number(avg_volume_m)}×1000/{_fmt_number(close)}) = "
            f"{_fmt_number(foreign_avg_daily_net)}/"
            f"{_fmt_number(avg_daily_volume_lots)} = "
            f"{ratio * 100:.1f}% {operator} {threshold * 100:.0f}%）"
        )

    parts.extend(
        [
            "股價站上 MA20",
            "突破日成交量未失控爆量",
        ]
    )
    return "；".join(parts) + "。符合 spec.md 3.2、7.8。"


def _build_excluded_reason(
    stock: dict[str, Any],
    metrics: dict[str, Any],
    direction: str,
    ratio: float,
    threshold: float,
    failed_check: str,
) -> str:
    """Build the reason string for an excluded stock."""
    if failed_check == "trust_days":
        return (
            f"投信 10 日買超天數 {stock.get('trust_10d_buy_days')} < 7，"
            "不符合 Setup B 篩選條件（spec.md 3.2）。"
        )
    if failed_check == "trust_net":
        return (
            f"投信 10 日淨買超為負或零（{stock.get('trust_10d_net', 0)}），"
            "不符合 Setup B 篩選條件（spec.md 3.2）。"
        )
    if failed_check == "foreign_direction":
        foreign_10d_net = stock.get("foreign_10d_net", 0)
        close = float(metrics.get("close", 0))
        avg_volume_m = _avg_volume_m(metrics) or 0.0
        avg_daily_volume_lots = avg_volume_m * 1000 / close if close else 0.0
        foreign_avg_daily_net = foreign_10d_net / 10
        return (
            f"外資 10 日方向為 selling（"
            f"ratio = ({_fmt_number(foreign_10d_net)}/10)/"
            f"({_fmt_number(avg_volume_m)}×1000/{_fmt_number(close)}) = "
            f"{_fmt_number(foreign_avg_daily_net)}/"
            f"{_fmt_number(avg_daily_volume_lots)} = "
            f"{ratio * 100:.1f}% < -{threshold * 100:.0f}%），"
            "屬明顯大賣，不符合 Setup B 篩選條件（spec.md 3.2、7.8）。"
        )
    if failed_check == "close_vs_ma20":
        return "股價未站上 MA20，不符合 Setup B 篩選條件（spec.md 3.2）。"
    if failed_check == "breakout_data":
        return "缺少突破資料（breakout_price/date/volume），無法產生 Setup B 候選股。"
    return "不符合 Setup B 篩選條件。"


def _build_issue_body(candidate: dict[str, Any]) -> str:
    """Build the Setup B Issue body markdown from a candidate dict.

    The corresponding GitHub Issue should be created with the labels:
    `setup-b,screened`.
    """
    lines = [
        "## Setup B 候選股登記",
        "",
        f"- **ticker**: {candidate['ticker']}",
        f"- **screen_date**: {candidate['screen_date']}",
        f"- **avg_volume_20d_m**: {candidate['avg_volume_20d_m']}",
        f"- **trust_10d_net**: {candidate['trust_10d_net']}",
        f"- **trust_10d_buy_days**: {candidate['trust_10d_buy_days']}",
        f"- **foreign_10d_direction**: {candidate['foreign_10d_direction']}",
        f"- **close_vs_ma20**: {candidate['close_vs_ma20']}",
        f"- **breakout_price**: {candidate['breakout_price']}",
        f"- **breakout_date**: {candidate['breakout_date']}",
        f"- **breakout_volume_m**: {candidate['breakout_volume_m']}",
        f"- **entry_zone**: {candidate['entry_zone']}",
        f"- **stop_loss_price**: {candidate['stop_loss_price']}",
        "- **position_size_lots**: ⚠️ 待人工填寫",
        "- **risk_r_pct**: ⚠️ 待人工填寫",
        f"- **artifact_run_id**: {candidate['artifact_run_id']}",
    ]
    return "\n".join(lines)


def screen_setup_b(
    stocks: list[dict[str, Any]],
    price_fetcher: Callable[[str, str], dict[str, Any] | None],
    screen_date: str,
    foreign_direction_threshold: float = 0.05,
    artifact_run_id: str | None = None,
) -> dict[str, Any]:
    """Pure Setup B screening function.

    Args:
        stocks: List of stock dicts with at least ticker, name, trust_10d_net,
            trust_10d_buy_days, foreign_10d_net, and breakout fields.
        price_fetcher: Callable(ticker, 'YYYYMMDD') -> price metrics dict or None.
            Expected metrics: close, ma20, avg_volume_20d_m or avg_volume_20d,
            and optionally close_vs_ma20.
        screen_date: Date string in 'YYYY-MM-DD' format.
        foreign_direction_threshold: Ratio threshold for buying/selling per 7.8.
        artifact_run_id: Workflow run ID to record in candidates. Defaults to
            the GITHUB_RUN_ID environment variable or 'manual'.

    Returns:
        Dict with screen_date, setup_b_candidates, excluded, and oracle metadata.
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
        if metrics is None:
            continue

        close = float(metrics.get("close", 0))
        avg_volume_m = _avg_volume_m(metrics)
        close_vs_ma20 = _close_vs_ma20(metrics)

        trust_10d_net = stock.get("trust_10d_net", 0)
        trust_10d_buy_days = stock.get("trust_10d_buy_days", 0)

        if trust_10d_net <= 0:
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock, metrics, "", 0.0, foreign_direction_threshold, "trust_net"
                    ),
                }
            )
            continue

        if trust_10d_buy_days < 7:
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock,
                        metrics,
                        "",
                        0.0,
                        foreign_direction_threshold,
                        "trust_days",
                    ),
                }
            )
            continue

        foreign_10d_net = stock.get("foreign_10d_net", 0)
        direction = _compute_foreign_10d_direction(
            foreign_10d_net,
            close,
            avg_volume_m,
            foreign_direction_threshold,
        )

        ratio = 0.0
        if direction != "neutral" and close and avg_volume_m:
            avg_daily_volume_lots = avg_volume_m * 1000 / close
            if avg_daily_volume_lots:
                ratio = (foreign_10d_net / 10) / avg_daily_volume_lots

        if direction == "selling":
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock,
                        metrics,
                        direction,
                        ratio,
                        foreign_direction_threshold,
                        "foreign_direction",
                    ),
                }
            )
            continue

        if close_vs_ma20 != "above":
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock,
                        metrics,
                        direction,
                        ratio,
                        foreign_direction_threshold,
                        "close_vs_ma20",
                    ),
                }
            )
            continue

        breakout_price = stock.get("breakout_price")
        breakout_date = stock.get("breakout_date")
        breakout_volume_m = stock.get("breakout_volume_m")
        if breakout_price is None or breakout_date is None or breakout_volume_m is None:
            excluded.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "should_include": False,
                    "reason": _build_excluded_reason(
                        stock,
                        metrics,
                        direction,
                        ratio,
                        foreign_direction_threshold,
                        "breakout_data",
                    ),
                }
            )
            continue

        entry_zone = f"突破價 {float(breakout_price):.2f} 之上且量縮"
        # Reference stop-loss price used by the screener. The actual stop-loss
        # is applied by the signal monitor based on entry_price and setup_type.
        stop_loss_price = round(close * 0.93)

        reason = _build_pass_reason(
            stock, metrics, direction, ratio, foreign_direction_threshold
        )

        candidates.append(
            {
                "ticker": ticker,
                "name": name,
                "screen_date": screen_date,
                "avg_volume_20d_m": _rounded_volume_m(avg_volume_m),
                "trust_10d_net": trust_10d_net,
                "trust_10d_buy_days": trust_10d_buy_days,
                "foreign_10d_direction": direction,
                "close_vs_ma20": close_vs_ma20,
                "breakout_price": breakout_price,
                "breakout_date": breakout_date,
                "breakout_volume_m": breakout_volume_m,
                "entry_zone": entry_zone,
                "stop_loss_price": stop_loss_price,
                "position_size_lots": "待人工填寫",
                "risk_r_pct": "待人工填寫",
                "artifact_run_id": artifact_run_id,
                "should_include": True,
                "reason": reason,
            }
        )

    return {
        "screen_date": screen_date,
        "setup_b_candidates": candidates,
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

    foreign_direction_threshold = float(
        os.environ.get("FOREIGN_10D_DIRECTION_THRESHOLD", "0.05")
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
    result = screen_setup_b(
        stocks,
        price_fetcher=fetch_price_metrics,
        screen_date=today_str,
        foreign_direction_threshold=foreign_direction_threshold,
    )
    candidates = result["setup_b_candidates"]

    os.makedirs(_SCREENER_DIR, exist_ok=True)
    output_path = os.path.join(
        _SCREENER_DIR, f"screener_result_b_{today_compact}.json"
    )
    result_payload = {
        "screen_date": today_str,
        "record_count": len(candidates),
        "candidates": candidates,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    print(
        f"OK: {today_str} Setup B 篩選完成，共 {len(candidates)} 檔，已寫入 {output_path}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
