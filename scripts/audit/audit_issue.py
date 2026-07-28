"""Audit Action: validate required fields on a GitHub Issue before it moves forward."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any


_REQUIRED_FIELDS: dict[str, list[str]] = {
    "a": [
        "ticker",
        "screen_date",
        "avg_volume_20d_m",
        "foreign_5d_net",
        "trust_5d_net",
        "close_vs_ma20",
        "ma20_direction",
        "entry_zone",
        "stop_loss_price",
        "position_size_lots",
        "risk_r_pct",
        "artifact_run_id",
    ],
    "b": [
        "ticker",
        "screen_date",
        "avg_volume_20d_m",
        "trust_10d_net",
        "trust_10d_buy_days",
        "foreign_10d_direction",
        "close_vs_ma20",
        "breakout_price",
        "entry_zone",
        "stop_loss_price",
        "position_size_lots",
        "risk_r_pct",
        "artifact_run_id",
    ],
    "c": [
        "ticker",
        "screen_date",
        "market_cap_b",
        "foreign_20d_net",
        "foreign_recent_3d",
        "price_bottom_status",
        "entry_day",
        "entry_zone",
        "stop_loss_price",
        "position_size_lots",
        "risk_r_pct",
        "artifact_run_id",
    ],
}

_PLACEHOLDER = "⚠️ 待人工填寫"


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _get_issue(number: int) -> dict[str, Any] | None:
    result = _run_gh(
        ["issue", "view", str(number), "--json", "body,labels,number,title"]
    )
    if result.returncode != 0:
        print(f"ERROR: 無法讀取 Issue #{number}: {result.stderr.strip()}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _determine_setup(issue: dict[str, Any]) -> str | None:
    labels = issue.get("labels", []) or []
    names = {lbl.get("name", "").lower() for lbl in labels}
    if "setup-a" in names:
        return "a"
    if "setup-b" in names:
        return "b"
    if "setup-c" in names:
        return "c"

    title = (issue.get("title", "") or "").lower()
    if "setup-a" in title or "setup a" in title:
        return "a"
    if "setup-b" in title or "setup b" in title:
        return "b"
    if "setup-c" in title or "setup c" in title:
        return "c"

    return None


def _parse_field(body: str, field: str) -> str | None:
    pattern = re.compile(r"[-*]\s*\*\*" + re.escape(field) + r"\*\*\s*[:：]\s*(.*)")
    for line in body.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def _has_label(issue: dict[str, Any], label: str) -> bool:
    labels = issue.get("labels", []) or []
    return any(lbl.get("name") == label for lbl in labels)


def _add_label(number: int, label: str) -> bool:
    result = _run_gh(["issue", "edit", str(number), "--add-label", label])
    if result.returncode != 0:
        print(f"WARNING: 無法加上 {label}: {result.stderr.strip()}")
        return False
    return True


def _remove_label(number: int, label: str) -> bool:
    result = _run_gh(["issue", "edit", str(number), "--remove-label", label])
    if result.returncode != 0:
        print(f"WARNING: 無法移除 {label}: {result.stderr.strip()}")
        return False
    return True


def _add_comment(number: int, body: str) -> bool:
    result = _run_gh(["issue", "comment", str(number), "--body", body])
    if result.returncode != 0:
        print(f"WARNING: 無法留言: {result.stderr.strip()}")
        return False
    return True


def _validate_numeric(value: str, field: str) -> tuple[bool, float | None]:
    """Return (is_valid, parsed_number)."""
    try:
        cleaned = value.replace(",", "")
        number = float(cleaned)
        return True, number
    except ValueError:
        return False, None


def _validate_field(field: str, value: str | None, setup: str) -> str | None:
    """Return error reason or None if valid."""
    if value is None:
        return "欄位不存在"

    if value == "":
        return "欄位為空"

    if field in ("position_size_lots", "risk_r_pct"):
        valid, parsed = _validate_numeric(value, field)
        if not valid:
            return f"必須為數字，目前為：{value}"
        if field == "risk_r_pct" and parsed is not None and parsed > 1.0:
            return f"risk_r_pct 不得超過 1.0%，目前為：{parsed}"
        return None

    if value == _PLACEHOLDER:
        return "仍為待人工填寫的佔位符"

    if field == "artifact_run_id":
        if not re.fullmatch(r"\d+", value):
            return f"必須為數字格式，目前為：{value}"
        return None

    return None


def audit_issue(number: int) -> dict[str, Any]:
    """Run audit on a single issue. Returns result dict."""
    result: dict[str, Any] = {
        "issue_number": number,
        "passed": False,
        "errors": [],
        "setup": None,
    }

    issue = _get_issue(number)
    if issue is None:
        result["errors"].append("無法讀取 Issue")
        return result

    setup = _determine_setup(issue)
    result["setup"] = setup
    if setup is None:
        result["errors"].append("無法判斷 Issue 屬於哪個 Setup（缺少 setup-a/b/c label）")
        return result

    required = _REQUIRED_FIELDS.get(setup)
    if not required:
        result["errors"].append(f"未知的 setup: {setup}")
        return result

    body = issue.get("body", "") or ""
    errors: list[tuple[str, str]] = []
    parsed_values: dict[str, str] = {}

    for field in required:
        value = _parse_field(body, field)
        parsed_values[field] = value or ""
        reason = _validate_field(field, value, setup)
        if reason:
            errors.append((field, reason))

    risk_r_pct_value = parsed_values.get("risk_r_pct")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if errors:
        result["passed"] = False
        result["errors"] = [{"field": f, "reason": r} for f, r in errors]

        if _has_label(issue, "auto-ok"):
            _remove_label(number, "auto-ok")
        _add_label(number, "data-missing")

        lines = [
            f"❌ **Audit 失敗** {timestamp}",
            "以下欄位未通過驗證：",
        ]
        for field, reason in errors:
            lines.append(f"- {field}：{reason}")
        lines.append("")
        lines.append("請修正後，在 Issue 下方留言 `/re-audit` 重新觸發驗證。")
        _add_comment(number, "\n".join(lines))
        print(f"FAIL: Issue #{number} Audit 未通過")
        return result

    result["passed"] = True

    if _has_label(issue, "data-missing"):
        _remove_label(number, "data-missing")

    comment_body = (
        f"✅ **Audit 通過** {timestamp}\n"
        f"所有必填欄位已驗證。risk_r_pct={risk_r_pct_value}%，符合規範。"
    )
    _add_comment(number, comment_body)
    print(f"OK: Issue #{number} Audit 通過")
    return result


def main() -> int:
    issue_number = os.environ.get("ISSUE_NUMBER")
    if not issue_number:
        print("ERROR: 缺少環境變數 ISSUE_NUMBER")
        return 1

    try:
        number = int(issue_number)
    except ValueError:
        print(f"ERROR: 無效的 Issue number: {issue_number}")
        return 1

    result = audit_issue(number)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
