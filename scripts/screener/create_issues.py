"""Create GitHub Issues for Setup A candidates."""

import json
import os
import subprocess
import sys
import time
from typing import Any


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _issue_exists(title_prefix: str, ticker: str) -> bool:
    """Return True if an open issue with the given title prefix and ticker exists."""
    search_term = f"{title_prefix} {ticker}"
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--search",
            f"in:title {search_term}",
            "--json",
            "number",
        ]
    )
    if result.returncode != 0:
        return False
    try:
        issues = json.loads(result.stdout)
        return len(issues) > 0
    except json.JSONDecodeError:
        return False


def _build_body(candidate: dict[str, Any]) -> str:
    """Build the Issue body from candidate fields."""
    lines = [
        "## Setup A 候選股登記",
        "",
        f"- **ticker**: {candidate['ticker']}",
        f"- **screen_date**: {candidate['screen_date']}",
        f"- **avg_volume_20d_m**: {candidate['avg_volume_20d_m']}",
        f"- **foreign_5d_net**: {candidate['foreign_5d_net']}",
        f"- **trust_5d_net**: {candidate['trust_5d_net']}",
        f"- **close_vs_ma20**: {'above' if candidate['close'] > candidate['ma20'] else 'below'}",
        f"- **ma20_direction**: {candidate['ma20_direction']}",
        f"- **entry_zone**: {candidate['entry_zone']}",
        f"- **stop_loss_price**: {candidate['stop_loss_price']}",
        f"- **position_size_lots**: ⚠️ 待人工填寫",
        f"- **risk_r_pct**: ⚠️ 待人工填寫",
        f"- **artifact_run_id**: {os.environ.get('GITHUB_RUN_ID', 'manual')}",
    ]
    return "\n".join(lines)


def _add_to_project(issue_number: int, project_number: str | None) -> bool:
    """Add the issue to the configured GitHub Project, if any."""
    if not project_number:
        return False
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return False
    result = _run_gh(
        [
            "project",
            "item-add",
            project_number,
            "--owner",
            repo.split("/")[0],
            "--issue",
            str(issue_number),
        ]
    )
    return result.returncode == 0


def create_issue(candidate: dict[str, Any], project_number: str | None = None) -> int | None:
    """Create a GitHub Issue for one candidate. Returns issue number or None."""
    screen_date = candidate["screen_date"].replace("-", "")
    title = f"[Setup-A][{screen_date}] {candidate['ticker']} {candidate['name']}"

    if _issue_exists(f"[Setup-A][{screen_date}]", candidate["ticker"]):
        print(f"SKIP: {candidate['ticker']} 已有開啟中的 Issue")
        return None

    body = _build_body(candidate)
    result = _run_gh(
        [
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--label",
            "setup-a,screened",
        ]
    )

    if result.returncode != 0:
        print(f"ERROR: 無法建立 {candidate['ticker']} 的 Issue")
        print(result.stderr)
        return None

    # gh issue create returns the issue URL; extract the number from the URL.
    url = result.stdout.strip()
    print(f"OK: 建立 Issue {url}")

    issue_number = None
    if "/" in url:
        try:
            issue_number = int(url.split("/")[-1])
        except ValueError:
            pass

    if issue_number and project_number:
        if _add_to_project(issue_number, project_number):
            print(f"OK: Issue #{issue_number} 已加入 Project")
        else:
            print(f"WARNING: Issue #{issue_number} 無法加入 Project")

    return issue_number


def main() -> int:
    """Entry point. Returns shell exit code."""
    if len(sys.argv) < 2:
        print("Usage: python create_issues.py <screener_result_a_YYYYMMDD.json>")
        return 1

    result_path = sys.argv[1]
    if not os.path.exists(result_path):
        print(f"ERROR: 找不到結果檔案: {result_path}")
        return 1

    with open(result_path, encoding="utf-8") as f:
        payload = json.load(f)

    project_number = os.environ.get("GH_PROJECT_NUMBER")

    for candidate in payload.get("candidates", []):
        create_issue(candidate, project_number=project_number)
        time.sleep(2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
