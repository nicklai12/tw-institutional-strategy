"""Signal Monitor: daily exit signal checks for holding issues."""

import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from typing import Any

import requests

_REPORT_DIR = "data/monitor"
_RAW_DIR = "data/raw"
_PRICE_API_BASE = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

_SETUP_STOP_LOSS_PCT = {
    "a": 7.0,
    "b": 6.0,
    "c": 5.0,
}

_SETUP_B_VOLUME_CONTRACTION_RATIO = 0.8


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
        data = response.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None
    finally:
        # Be polite to TWSE endpoints.
        time.sleep(0.5)


def _to_roc_date(yyyymmdd: str) -> str:
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


def _parse_field(text: str, key: str) -> str | None:
    pattern = re.compile(r"[-*]\s*\*\*" + re.escape(key) + r"\*\*\s*[:：]\s*(.+)")
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def _normalize_setup_type(value: str | None) -> str | None:
    if not value:
        return None
    value = value.lower().strip()
    if value in ("a", "b", "c"):
        return value
    if "setup-a" in value or "setup a" in value:
        return "a"
    if "setup-b" in value or "setup b" in value:
        return "b"
    if "setup-c" in value or "setup c" in value:
        return "c"
    return None


def _extract_ticker_from_title(title: str) -> str | None:
    match = re.search(r"\[Setup-[A-Za-z]\]\[\d{8}\]\s+(\d{4})\s", title)
    if match:
        return match.group(1)
    return None


def get_holding_issues() -> list[dict[str, Any]]:
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "holding",
            "--json",
            "number,title,labels",
            "--limit",
            "1000",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法讀取 holding Issues: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def get_auto_ok_issues() -> list[dict[str, Any]]:
    """Return open issues labeled 'auto-ok'."""
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "auto-ok",
            "--json",
            "number,title,labels",
            "--limit",
            "1000",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法讀取 auto-ok Issues: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def get_issue_details(number: int) -> dict[str, Any] | None:
    result = _run_gh(
        [
            "issue",
            "view",
            str(number),
            "--comments",
            "--json",
            "number,title,body,labels,comments",
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法讀取 Issue #{number} 詳細內容: {result.stderr.strip()}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def parse_entry_info(issue: dict[str, Any], require_entry: bool = True) -> dict[str, Any] | None:
    """Extract ticker, setup_type, entry_date and entry_price from issue body/comments.

    Args:
        issue: GitHub issue dict with title, body, labels and comments.
        require_entry: If True, entry_date and entry_price must be present.
            Use False for auto-ok issues that have not been entered yet.
    """
    title = issue.get("title", "")
    body = issue.get("body", "") or ""
    comments = issue.get("comments", []) or []
    try:
        comments = sorted(
            comments,
            key=lambda c: datetime.fromisoformat(
                c.get("createdAt", "1970-01-01T00:00:00Z").replace("Z", "+00:00")
            ),
        )
    except Exception:
        pass

    texts = [body] + [c.get("body", "") or "" for c in comments]

    setup_type = None
    entry_date = None
    entry_price = None
    ticker = None
    breakout_date = None
    breakout_price = None
    breakout_volume_m = None
    entry_day = None
    foreign_buy_streak_day = None

    for text in texts:
        if setup_type is None:
            setup_type = _normalize_setup_type(_parse_field(text, "setup_type"))
        if entry_date is None:
            entry_date = _parse_field(text, "entry_date")
        if entry_price is None:
            price_str = _parse_field(text, "entry_price")
            if price_str:
                try:
                    entry_price = float(price_str.replace(",", ""))
                except ValueError:
                    entry_price = None
        if ticker is None:
            ticker = _parse_field(text, "ticker")
        if breakout_date is None:
            breakout_date = _parse_field(text, "breakout_date")
        if breakout_price is None:
            breakout_price_str = _parse_field(text, "breakout_price")
            if breakout_price_str:
                try:
                    breakout_price = float(breakout_price_str.replace(",", ""))
                except ValueError:
                    breakout_price = None
        if breakout_volume_m is None:
            breakout_volume_m_str = _parse_field(text, "breakout_volume_m")
            if breakout_volume_m_str:
                try:
                    breakout_volume_m = float(breakout_volume_m_str.replace(",", ""))
                except ValueError:
                    breakout_volume_m = None
        if entry_day is None:
            entry_day_str = _parse_field(text, "entry_day")
            if entry_day_str:
                try:
                    entry_day = int(entry_day_str.replace(",", ""))
                except ValueError:
                    entry_day = None
        if foreign_buy_streak_day is None:
            foreign_buy_streak_day_str = _parse_field(text, "foreign_buy_streak_day")
            if foreign_buy_streak_day_str:
                try:
                    foreign_buy_streak_day = int(foreign_buy_streak_day_str.replace(",", ""))
                except ValueError:
                    foreign_buy_streak_day = None

    if ticker is None:
        ticker = _extract_ticker_from_title(title)

    if setup_type is None:
        labels = issue.get("labels", []) or []
        label_names = {lbl.get("name", "").lower() for lbl in labels}
        if "setup-a" in label_names:
            setup_type = "a"
        elif "setup-b" in label_names:
            setup_type = "b"
        elif "setup-c" in label_names:
            setup_type = "c"
        else:
            setup_type = _normalize_setup_type(title)

    if require_entry and not all([ticker, setup_type, entry_date, entry_price]):
        return None
    if not require_entry and not all([ticker, setup_type]):
        return None

    return {
        "ticker": ticker,
        "setup_type": setup_type,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "breakout_date": breakout_date,
        "breakout_price": breakout_price,
        "breakout_volume_m": breakout_volume_m,
        "entry_day": entry_day,
        "foreign_buy_streak_day": foreign_buy_streak_day,
    }


def load_raw_files(raw_dir: str = _RAW_DIR) -> list[tuple[str, dict[str, Any]]]:
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


def _get_record_for_date(
    raw_data: list[tuple[str, dict[str, Any]]], ticker: str, date_str: str
) -> dict[str, Any] | None:
    for d, payload in raw_data:
        if d == date_str:
            for record in payload.get("data", []):
                if record.get("ticker") == ticker:
                    return record
            return None
    return None


def get_recent_nets(
    raw_data: list[tuple[str, dict[str, Any]]],
    ticker: str,
    field: str,
    n: int,
) -> list[float | None]:
    """Return the last n daily net values (oldest first) for the given field."""
    values: list[float | None] = []
    for date_str, payload in raw_data[-n:]:
        record = None
        for rec in payload.get("data", []):
            if rec.get("ticker") == ticker:
                record = rec
                break
        if record is None:
            values.append(None)
        else:
            values.append(record.get(field))
    return values


def _sign(value: float | None) -> str:
    if value is None:
        return "N/A"
    return "正" if value > 0 else "負" if value < 0 else "平"


def count_trading_days(
    raw_data: list[tuple[str, dict[str, Any]]], entry_date: str, today_str: str
) -> int:
    count = 0
    for date_str, _ in raw_data:
        if entry_date <= date_str <= today_str:
            count += 1
    return count


def count_trading_days_after_breakout(
    raw_data: list[tuple[str, dict[str, Any]]], breakout_date: str, today_str: str
) -> int:
    """Count trading days strictly after breakout_date up to and including today."""
    count = 0
    for date_str, _ in raw_data:
        if breakout_date < date_str <= today_str:
            count += 1
    return count


def compute_foreign_buy_streak_day(
    raw_data: list[tuple[str, dict[str, Any]]], ticker: str
) -> int:
    """Count consecutive foreign_net > 0 days ending at the most recent raw date."""
    count = 0
    for date_str, payload in reversed(raw_data):
        record = None
        for rec in payload.get("data", []):
            if rec.get("ticker") == ticker:
                record = rec
                break
        if record is None:
            break
        if record.get("foreign_net", 0) > 0:
            count += 1
        else:
            break
    return count


def fetch_stock_history(ticker: str, date_str: str) -> list[dict[str, Any]] | None:
    """Fetch daily K-lines up to and including date_str."""
    target_roc = _to_roc_date(date_str)
    current_month = _month_start_date(date_str)
    previous_month = _prev_month_date(date_str)

    parsed: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for month_date in (previous_month, current_month):
        url = f"{_PRICE_API_BASE}?response=json&stockNo={ticker}&date={month_date}"
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
            high_i = fields.index("最高價")
            low_i = fields.index("最低價")
            turnover_i = fields.index("成交金額")
        except ValueError:
            continue

        for row in rows:
            if len(row) <= max(date_i, close_i, high_i, low_i, turnover_i):
                continue
            try:
                item = {
                    "date": row[date_i],
                    "close": float(str(row[close_i]).replace(",", "")),
                    "high": float(str(row[high_i]).replace(",", "")),
                    "low": float(str(row[low_i]).replace(",", "")),
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

    if index is None:
        return None

    return parsed[: index + 1]


def compute_price_metrics(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not history:
        return None

    closes = [item["close"] for item in history]
    today_close = closes[-1]

    ma20 = None
    ma20_close_direction = "N/A"
    if len(closes) >= 20:
        ma20 = round(sum(closes[-20:]) / 20, 2)
        ma20_close_direction = "站上" if today_close > ma20 else "跌破"

    ma10 = None
    ma5 = None
    if len(closes) >= 10:
        ma10 = round(sum(closes[-10:]) / 10, 2)
    if len(closes) >= 5:
        ma5 = round(sum(closes[-5:]) / 5, 2)

    prev_close_below_ma20 = False
    if len(closes) >= 22:
        prev_close = closes[-2]
        prev_ma20 = sum(closes[-22:-2]) / 20
        prev_close_below_ma20 = prev_close < prev_ma20

    recent_low_20d = None
    recent_low_10d = None
    if history:
        window_20d = history[-20:]
        recent_low_20d = round(min(item.get("low", item["close"]) for item in window_20d), 2)
        window_10d = history[-10:]
        recent_low_10d = round(min(item.get("low", item["close"]) for item in window_10d), 2)

    today_item = history[-1] if history else {}
    volume_today_m = None
    turnover = today_item.get("turnover")
    if turnover is not None:
        volume_today_m = round(turnover / 1_000_000, 2)

    today_low = today_item.get("low")
    today_high = today_item.get("high")

    return {
        "close": round(today_close, 2),
        "ma20": ma20,
        "ma20_close_direction": ma20_close_direction,
        "ma10": ma10,
        "ma5": ma5,
        "prev_close_below_ma20": prev_close_below_ma20,
        "today_close_below_ma20": ma20 is not None and today_close < ma20,
        "recent_low_20d": recent_low_20d,
        "recent_low_10d": recent_low_10d,
        "volume_today_m": volume_today_m,
        "today_low": today_low,
        "today_high": today_high,
    }


def fetch_price_metrics(ticker: str, date_str: str) -> dict[str, Any] | None:
    """Fetch daily price history and compute close, MA5 and MA20.

    Uses the same TWSE endpoint as fetch_stock_history to avoid the
    rate-limiting / blocking issues seen with the setup_a endpoint in
    GitHub Actions.
    """
    history = fetch_stock_history(ticker, date_str)
    if history is None:
        return None
    metrics = compute_price_metrics(history)
    if metrics is None:
        return None
    ma5 = metrics.get("ma5")
    ma20 = metrics.get("ma20")
    if ma5 is None or ma20 is None:
        return None
    return {
        "close": metrics["close"],
        "ma5": ma5,
        "ma20": ma20,
    }


def evaluate_signals(
    setup_type: str,
    entry_price: float,
    entry_date: str,
    metrics: dict[str, Any],
    raw_data: list[tuple[str, dict[str, Any]]],
    ticker: str,
    today_str: str,
) -> dict[str, Any]:
    """Evaluate exit/stop-loss signals for a holding issue."""
    close = metrics["close"]
    pnl_pct = round((close - entry_price) / entry_price * 100, 2) if entry_price else 0.0
    stop_loss_pct = _SETUP_STOP_LOSS_PCT.get(setup_type, 5.0)
    stoploss_triggered = pnl_pct <= -stop_loss_pct

    foreign_3d = get_recent_nets(raw_data, ticker, "foreign_net", 3)
    trust_3d = get_recent_nets(raw_data, ticker, "trust_net", 3)

    foreign_signs = [_sign(v) for v in foreign_3d]
    trust_signs = [_sign(v) for v in trust_3d]

    foreign_sell_2d = all(v is not None and v < 0 for v in foreign_3d[-2:])
    foreign_sell_3d = all(v is not None and v < 0 for v in foreign_3d)
    trust_sell_2d = all(v is not None and v < 0 for v in trust_3d[-2:])
    trust_sell_3d = all(v is not None and v < 0 for v in trust_3d)

    exit_signals: list[str] = []
    partial_signals: list[str] = []
    stopprofit_reminder = False

    if setup_type == "a":
        if foreign_sell_3d or trust_sell_3d:
            exit_signals.append("E1 法人轉弱")
        if metrics.get("today_close_below_ma20") and metrics.get("prev_close_below_ma20"):
            exit_signals.append("E2 價格轉弱")
        trading_days = count_trading_days(raw_data, entry_date.replace("-", ""), today_str.replace("-", ""))
        if trading_days >= 20:
            exit_signals.append("E3 時間停利")

    elif setup_type == "b":
        if trust_sell_2d:
            partial_signals.append("E1 投信連續賣超（先出一半）")
        below_ma10 = metrics.get("ma10") is not None and close < metrics["ma10"]
        below_low = metrics.get("recent_low_20d") is not None and close < metrics["recent_low_20d"]
        if trust_sell_2d and (below_ma10 or below_low):
            exit_signals.append("E2 跌破 MA10/前低（全出）")

    elif setup_type == "c":
        if foreign_sell_2d:
            exit_signals.append("E1 外資連續轉賣")
        below_support = (
            metrics.get("recent_low_10d") is not None
            and close < metrics["recent_low_10d"]
        )
        if below_support:
            exit_signals.append("E2 跌破整理區間下緣")
        if 8.0 <= pnl_pct <= 12.0:
            stopprofit_reminder = True

    return {
        "pnl_pct": pnl_pct,
        "close": close,
        "foreign_signs": foreign_signs,
        "trust_signs": trust_signs,
        "ma20": metrics.get("ma20"),
        "ma20_close_direction": metrics.get("ma20_close_direction", "N/A"),
        "ma10": metrics.get("ma10"),
        "recent_low_20d": metrics.get("recent_low_20d"),
        "recent_low_10d": metrics.get("recent_low_10d"),
        "exit_signals": exit_signals,
        "partial_signals": partial_signals,
        "stoploss_triggered": stoploss_triggered,
        "stopprofit_reminder": stopprofit_reminder,
    }


def check_entry_signal(
    ticker: str,
    date_str: str | None = None,
    setup_type: str = "a",
    issue_info: dict[str, Any] | None = None,
    raw_data: list[tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Check if today's close satisfies the entry rule for the given setup.

    Setup A: close falls between MA5 and MA20.
    Setup B: breakout follow-through with volume contraction.
    Setup C: foreign buy streak day in [2, 4].

    Returns None if required price metrics cannot be fetched.
    """
    if date_str is None:
        date_str = _today_compact()

    metrics = fetch_price_metrics(ticker, date_str)
    if metrics is None:
        return None

    close = metrics.get("close")
    if close is None:
        return None

    if setup_type == "a":
        ma5 = metrics.get("ma5")
        ma20 = metrics.get("ma20")
        if ma5 is None or ma20 is None:
            return None
        lower = min(ma5, ma20)
        upper = max(ma5, ma20)
        triggered = lower <= close <= upper
        return {
            "triggered": triggered,
            "close": close,
            "ma5": ma5,
            "ma20": ma20,
            "lower": round(lower, 2),
            "upper": round(upper, 2),
        }

    # Setup B and C need high/low/volume from the full history.
    history = fetch_stock_history(ticker, date_str)
    if history is None:
        return None
    full_metrics = compute_price_metrics(history)
    if full_metrics is None:
        return None

    if setup_type == "b":
        issue_info = issue_info or {}
        breakout_date = issue_info.get("breakout_date")
        breakout_price = issue_info.get("breakout_price")
        breakout_volume_m = issue_info.get("breakout_volume_m")
        volume_today_m = full_metrics.get("volume_today_m")
        if (
            breakout_date is None
            or breakout_price is None
            or breakout_volume_m is None
            or volume_today_m is None
            or raw_data is None
        ):
            return None
        trading_days_after_breakout = count_trading_days_after_breakout(
            raw_data, breakout_date.replace("-", ""), date_str
        )
        triggered = (
            trading_days_after_breakout in (1, 2)
            and close >= breakout_price
            and volume_today_m <= breakout_volume_m * _SETUP_B_VOLUME_CONTRACTION_RATIO
        )
        return {
            "triggered": triggered,
            "close": close,
            "volume_today_m": volume_today_m,
            "breakout_price": breakout_price,
            "breakout_volume_m": breakout_volume_m,
            "trading_days_after_breakout": trading_days_after_breakout,
        }

    if setup_type == "c":
        if raw_data is None:
            return None
        foreign_buy_streak_day = compute_foreign_buy_streak_day(raw_data, ticker)
        today_low = full_metrics.get("today_low")
        today_high = full_metrics.get("today_high")
        triggered = 2 <= foreign_buy_streak_day <= 4 and close > 0
        entry_zone = None
        if triggered and today_low is not None and today_high is not None:
            entry_zone = [round(today_low, 2), round(today_high, 2)]
        return {
            "triggered": triggered,
            "close": close,
            "foreign_buy_streak_day": foreign_buy_streak_day,
            "entry_zone": entry_zone,
            "today_low": today_low,
            "today_high": today_high,
        }

    return None


def build_monitor_comment(result: dict[str, Any], setup_type: str) -> str:
    lines = [
        "---",
        f"📊 **每日監控更新** {date.today().strftime('%Y-%m-%d')}",
        f"- 當日收盤：{result['close']}",
        f"- 相對進場損益：{result['pnl_pct']}%",
        f"- 外資近3日：{'/'.join(result['foreign_signs'])}",
        f"- 投信近3日：{'/'.join(result['trust_signs'])}",
        f"- MA20：{result['ma20']}（{result['ma20_close_direction']}）",
    ]

    if setup_type == "b":
        lines.append(f"- MA10：{result['ma10']}")
        lines.append(f"- 前低（20日）：{result['recent_low_20d']}")

    if setup_type == "c":
        lines.append(f"- 整理區間下緣（10日低）：{result['recent_low_10d']}")

    for signal in result["partial_signals"]:
        lines.append(f"- **出場信號：{signal} 觸發**")

    for signal in result["exit_signals"]:
        lines.append(f"- **出場信號：{signal} 觸發**")

    if result["stoploss_triggered"]:
        lines.append("- 🛑 停損提醒")

    if result["stopprofit_reminder"]:
        lines.append(f"- 💡 停利提醒：損益達 +{result['pnl_pct']}%")

    if result["exit_signals"] or result["stoploss_triggered"]:
        lines.append("")
        lines.append("⚠️ 出場提醒：請確認後手動結算並關閉 Issue")

    lines.append("---")
    return "\n".join(lines)


def add_label(number: int, label: str) -> bool:
    result = _run_gh(["issue", "edit", str(number), "--add-label", label])
    if result.returncode != 0:
        print(f"WARNING: 無法加上 {label} 到 Issue #{number}: {result.stderr.strip()}")
        return False
    return True


def add_comment(number: int, body: str) -> bool:
    result = _run_gh(["issue", "comment", str(number), "--body", body])
    if result.returncode != 0:
        print(f"WARNING: 無法對 Issue #{number} 留言: {result.stderr.strip()}")
        return False
    return True


def main() -> int:
    today_str = _today_str()
    today_compact = _today_compact()

    raw_data = load_raw_files()
    if not raw_data:
        print("ERROR: 找不到 raw 數據")
        return 1

    latest_raw_date = raw_data[-1][0]
    print(f"OK: 使用 raw 數據最新日期 {latest_raw_date}")

    holding_issues = get_holding_issues()
    if not holding_issues:
        print("OK: 目前沒有 holding Issue")

    processed = 0
    triggered_count = 0
    reports: list[dict[str, Any]] = []

    for issue_summary in holding_issues:
        number = issue_summary["number"]
        issue = get_issue_details(number)
        if issue is None:
            continue

        info = parse_entry_info(issue)
        if info is None:
            print(f"WARNING: Issue #{number} 缺少進場資訊，跳過")
            add_comment(
                number,
                "⚠️ Signal Monitor: 缺少進場資訊（entry_date / entry_price / setup_type），無法監控",
            )
            add_label(number, "data-missing")
            continue

        ticker = info["ticker"]
        setup_type = info["setup_type"]
        entry_price = info["entry_price"]
        entry_date = info["entry_date"]

        history = fetch_stock_history(ticker, latest_raw_date)
        if history is None:
            print(f"WARNING: Issue #{number} ({ticker}) 無法取得股價資料，跳過")
            add_comment(
                number,
                f"⚠️ Signal Monitor: 無法取得 {ticker} 股價資料",
            )
            continue

        metrics = compute_price_metrics(history)
        if metrics is None:
            continue

        result = evaluate_signals(
            setup_type=setup_type,
            entry_price=entry_price,
            entry_date=entry_date,
            metrics=metrics,
            raw_data=raw_data,
            ticker=ticker,
            today_str=today_str,
        )

        comment_body = build_monitor_comment(result, setup_type)
        add_comment(number, comment_body)

        processed += 1
        reports.append(
            {
                "issue_number": number,
                "ticker": ticker,
                "setup_type": setup_type,
                "entry_price": entry_price,
                "close": result["close"],
                "pnl_pct": result["pnl_pct"],
                "exit_signals": result["exit_signals"],
                "partial_signals": result["partial_signals"],
                "stoploss_triggered": result["stoploss_triggered"],
                "stopprofit_reminder": result["stopprofit_reminder"],
            }
        )

    # Entry-signal scan for issues labeled auto-ok.
    auto_ok_issues = get_auto_ok_issues()
    if not auto_ok_issues:
        print("OK: 目前沒有 auto-ok Issue")

    for issue_summary in auto_ok_issues:
        number = issue_summary["number"]
        issue = get_issue_details(number)
        if issue is None:
            continue

        info = parse_entry_info(issue, require_entry=False)
        if info is None:
            print(f"WARNING: Issue #{number} 無法解析進場資訊，跳過")
            continue

        ticker = info["ticker"]
        setup_type = info["setup_type"]
        entry_zone = _parse_field(issue.get("body", "") or "", "entry_zone")

        signal = check_entry_signal(
            ticker, latest_raw_date, setup_type=setup_type, issue_info=info, raw_data=raw_data
        )
        if signal is None:
            print(f"WARNING: Issue #{number} ({ticker}) 無法取得進場價格指標，跳過")
            continue

        if signal["triggered"]:
            print(f"OK: Issue #{number} ({ticker}) 符合進場條件")
            result = _run_gh(
                [
                    "issue",
                    "edit",
                    str(number),
                    "--remove-label",
                    "screened",
                    "--remove-label",
                    "auto-ok",
                    "--add-label",
                    "signal-confirmed",
                ]
            )
            if result.returncode != 0:
                print(
                    f"WARNING: 無法更新 Issue #{number} 的 labels: {result.stderr.strip()}"
                )
                continue

            comment_lines = [
                "---",
                f"📊 **進場訊號確認** {_today_str()}",
                f"- 當日收盤：{signal['close']}",
            ]
            if setup_type == "a":
                comment_lines.extend(
                    [
                        f"- MA5：{signal['ma5']}",
                        f"- MA20：{signal['ma20']}",
                    ]
                )
            elif setup_type == "b":
                comment_lines.extend(
                    [
                        f"- 突破價：{signal['breakout_price']}",
                        f"- 今日成交量（百萬）：{signal['volume_today_m']}",
                        f"- 突破日成交量（百萬）：{signal['breakout_volume_m']}",
                        f"- 突破後交易日數：{signal['trading_days_after_breakout']}",
                    ]
                )
            elif setup_type == "c":
                comment_lines.extend(
                    [
                        f"- 外資連買天數：{signal['foreign_buy_streak_day']}",
                        f"- 當日高低區間：[{signal['today_low']}, {signal['today_high']}]",
                    ]
                )
            if entry_zone:
                comment_lines.append(f"- 進場區間參考值：{entry_zone}")
            comment_lines.extend(
                [
                    "",
                    "✅ 訊號確認，符合進場條件",
                    "",
                    "已將本 Issue 標記為 signal-confirmed，請進行後續下單與建倉追蹤。",
                    "---",
                ]
            )
            add_comment(number, "\n".join(comment_lines))

    os.makedirs(_REPORT_DIR, exist_ok=True)
    report_path = os.path.join(_REPORT_DIR, f"monitor_report_{today_compact}.json")
    report = {
        "date": today_str,
        "raw_date": latest_raw_date,
        "processed_count": processed,
        "exit_triggered_count": triggered_count,
        "holdings": reports,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"OK: Monitor report written to {report_path}")
    print(f"processed={processed}, exit_triggered={triggered_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
