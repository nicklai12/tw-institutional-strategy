"""Create GitHub Issues for Setup A/B/C candidates."""

import json
import os
import subprocess
import sys
import time
from typing import Any

# Reuse the issue-body builders from the setup-specific screeners so that
# field names and formatting stay in sync with audit_issue.py.
from scripts.screener.setup_b import _build_issue_body as _build_setup_b_body
from scripts.screener.setup_c import _build_issue_body as _build_setup_c_body


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


def _build_setup_a_body(candidate: dict[str, Any]) -> str:
    """Build the Setup A Issue body from candidate fields."""
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
        f"- **artifact_run_id**: {candidate.get('artifact_run_id', os.environ.get('GITHUB_RUN_ID', 'manual'))}",
    ]
    return "\n".join(lines)


_SETUP_CONFIG: dict[str, dict[str, Any]] = {
    "a": {
        "candidate_key": "candidates",
        "title_prefix": "Setup-A",
        "label": "setup-a,screened",
        "body_builder": _build_setup_a_body,
    },
    "b": {
        "candidate_key": "setup_b_candidates",
        "title_prefix": "Setup-B",
        "label": "setup-b,screened",
        "body_builder": _build_setup_b_body,
    },
    "c": {
        "candidate_key": "setup_c_candidates",
        "title_prefix": "Setup-C",
        "label": "setup-c,screened",
        "body_builder": _build_setup_c_body,
    },
}


def detect_setup(result_path: str, payload: dict[str, Any]) -> str:
    """Detect setup type from filename or payload keys.

    Filename is the production source of truth because setup_a.py,
    setup_b.py, and setup_c.py all write files named
    screener_result_a_YYYYMMDD.json, screener_result_b_YYYYMMDD.json, and
    screener_result_c_YYYYMMDD.json respectively. Payload-key fallback
    supports test/oracle fixtures that use setup-specific candidate keys.
    """
    basename = os.path.basename(result_path)
    if "screener_result_b_" in basename:
        return "b"
    if "screener_result_c_" in basename:
        return "c"
    if "screener_result_a_" in basename:
        return "a"

    if "setup_b_candidates" in payload:
        return "b"
    if "setup_c_candidates" in payload:
        return "c"
    if "candidates" in payload:
        return "a"

    raise ValueError(
        f"無法從檔名或 payload 判斷 setup type: {result_path}. "
        "期望檔名包含 screener_result_a_/b_/c_，或 payload 包含 "
        "candidates/setup_b_candidates/setup_c_candidates。"
    )


def get_candidates(payload: dict[str, Any], setup: str) -> list[dict[str, Any]]:
    """Return the candidate list for the given setup."""
    key = _SETUP_CONFIG[setup]["candidate_key"]
    return payload.get(key, [])


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


def create_issue(
    candidate: dict[str, Any],
    project_number: str | None = None,
    setup: str = "a",
) -> int | None:
    """Create a GitHub Issue for one candidate. Returns issue number or None."""
    config = _SETUP_CONFIG[setup]
    screen_date = candidate["screen_date"].replace("-", "")
    title_prefix = config["title_prefix"]
    title = f"[{title_prefix}][{screen_date}] {candidate['ticker']} {candidate['name']}"

    if _issue_exists(f"[{title_prefix}][{screen_date}]", candidate["ticker"]):
        print(f"SKIP: {candidate['ticker']} 已有開啟中的 Issue")
        return None

    body = config["body_builder"](candidate)
    result = _run_gh(
        [
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--label",
            config["label"],
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
        print("Usage: python -m scripts.screener.create_issues <screener_result_*.json>")
        return 1

    result_path = sys.argv[1]
    if not os.path.exists(result_path):
        print(f"ERROR: 找不到結果檔案: {result_path}")
        return 1

    with open(result_path, encoding="utf-8") as f:
        payload = json.load(f)

    try:
        setup = detect_setup(result_path, payload)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    project_number = os.environ.get("GH_PROJECT_NUMBER")

    for candidate in get_candidates(payload, setup):
        create_issue(candidate, project_number=project_number, setup=setup)
        time.sleep(2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
