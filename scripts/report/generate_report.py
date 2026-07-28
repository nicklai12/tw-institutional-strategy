"""Report Agent: generate weekly performance and system-health report."""

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from typing import Any


_REPORT_DIR = "docs/data"
_HTML_PATH = "docs/index.html"
_TZ_TAIPEI = timezone(timedelta(hours=8))


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _today_taiwan() -> date:
    return datetime.now(_TZ_TAIPEI).date()


def _current_iso_week() -> tuple[int, int]:
    return datetime.now(_TZ_TAIPEI).isocalendar()[:2]


def _week_boundaries_taiwan(iso_year: int, iso_week: int) -> tuple[datetime, datetime]:
    """Return (week_start, week_end) in Asia/Taipei for the given ISO week."""
    # isocalendar uses Monday as first day.
    monday = datetime.strptime(f"{iso_year}-W{iso_week:02d}-1", "%G-W%V-%u")
    monday = monday.replace(tzinfo=_TZ_TAIPEI)
    sunday = monday + timedelta(days=7, microseconds=-1)
    return monday, sunday


def _parse_gh_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _list_all_issues(limit: int = 1000) -> list[dict[str, Any]]:
    result = _run_gh(
        [
            "issue",
            "list",
            "--state",
            "all",
            "--json",
            "number,title,labels,createdAt,body,comments",
            "--limit",
            str(limit),
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法讀取 Issues: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def _has_label(issue: dict[str, Any], label: str) -> bool:
    labels = issue.get("labels", []) or []
    return any(lbl.get("name") == label for lbl in labels)


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


def _issue_created_this_week(
    issue: dict[str, Any], week_start: datetime, week_end: datetime
) -> bool:
    created_at = issue.get("createdAt")
    if not created_at:
        return False
    try:
        created = _parse_gh_timestamp(created_at).astimezone(_TZ_TAIPEI)
    except ValueError:
        return False
    return week_start <= created <= week_end


def _repo_short() -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        return repo
    result = _run_gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _this_week_guardrail_artifacts(
    week_start: datetime, week_end: datetime
) -> list[dict[str, Any]]:
    """List guardrail-report artifacts created this week."""
    repo = _repo_short()
    if not repo:
        print("WARNING: 無法取得 repo 名稱，跳過 guardrail 統計")
        return []

    result = _run_gh(
        [
            "api",
            f"repos/{repo}/actions/artifacts",
            "--paginate",
            "--jq",
            '[.artifacts[] | select(.name | startswith("guardrail-report-")) | {name: .name, created_at: .created_at}]',
        ]
    )
    if result.returncode != 0:
        print(f"WARNING: 無法列出 artifacts: {result.stderr.strip()}")
        return []

    try:
        artifacts = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    this_week: list[dict[str, Any]] = []
    for artifact in artifacts:
        created_at = artifact.get("created_at")
        if not created_at:
            continue
        try:
            created = _parse_gh_timestamp(created_at).astimezone(_TZ_TAIPEI)
        except ValueError:
            continue
        if week_start <= created <= week_end:
            this_week.append(artifact)

    return this_week


def _extract_run_id_from_artifact_name(name: str) -> str | None:
    match = re.match(r"guardrail-report-(\d+)", name)
    if match:
        return match.group(1)
    return None


def _count_guardrail_triggers(
    artifacts: list[dict[str, Any]], week_start: datetime, week_end: datetime
) -> int:
    """Count guardrail artifacts from this week whose overall_pass is false."""
    triggered = 0
    for artifact in artifacts:
        name = artifact.get("name", "")
        run_id = _extract_run_id_from_artifact_name(name)
        if not run_id:
            continue

        with tempfile.TemporaryDirectory() as tmp_dir:
            download = _run_gh(
                [
                    "run",
                    "download",
                    run_id,
                    "--name",
                    name,
                    "--dir",
                    tmp_dir,
                ]
            )
            if download.returncode != 0:
                print(f"WARNING: 無法下載 artifact {name}: {download.stderr.strip()}")
                continue

            paths = glob.glob(os.path.join(tmp_dir, "data", "guardrail", "check_result_*.json"))
            if not paths:
                continue

            try:
                with open(paths[0], encoding="utf-8") as f:
                    report = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            if report.get("overall_pass") is False:
                triggered += 1

    return triggered


def _parse_entry_date_from_body(issue: dict[str, Any]) -> str | None:
    body = issue.get("body", "") or ""
    pattern = re.compile(r"[-*]\s*\*\*entry_date\*\*\s*[:：]\s*(.*)")
    for line in body.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def _parse_pnl_from_comments(issue: dict[str, Any]) -> str | None:
    """Return the latest pnl_pct string found in monitor comments, or None."""
    comments = issue.get("comments", []) or []
    # Newest first.
    for comment in reversed(comments):
        body = comment.get("body", "") or ""
        match = re.search(r"相對進場損益\s*[:：]\s*([-+]?\d+(?:\.\d+)?)\s*%", body)
        if match:
            return match.group(1)
    return None


def _compute_days_held(entry_date_str: str, report_date: date) -> int | None:
    try:
        entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (report_date - entry_date).days


def _compute_system_health(
    issues: list[dict[str, Any]],
    week_start: datetime,
    week_end: datetime,
    guardrail_triggered_count: int,
) -> dict[str, Any]:
    screened_this_week = [
        issue
        for issue in issues
        if _has_label(issue, "screened")
        and _issue_created_this_week(issue, week_start, week_end)
    ]
    total_screened_this_week = len(screened_this_week)

    if total_screened_this_week == 0:
        audit_pass_rate = 1.0
    else:
        passed_count = sum(
            1 for issue in screened_this_week if not _has_label(issue, "data-missing")
        )
        audit_pass_rate = round(passed_count / total_screened_this_week, 2)

    human_review_count = sum(
        1
        for issue in issues
        if _has_label(issue, "human-review")
        and _issue_created_this_week(issue, week_start, week_end)
    )

    return {
        "total_screened_this_week": total_screened_this_week,
        "audit_pass_rate": audit_pass_rate,
        "guardrail_triggered_count": guardrail_triggered_count,
        "human_review_count": human_review_count,
    }


def _compute_strategy_performance(issues: list[dict[str, Any]]) -> dict[str, Any]:
    performance: dict[str, Any] = {}
    for setup in ("a", "b", "c"):
        setup_label = f"setup-{setup}"
        closed = [
            issue
            for issue in issues
            if _has_label(issue, "closed")
            and (_has_label(issue, setup_label) or _determine_setup(issue) == setup)
        ]
        closed_count = len(closed)
        win_count = sum(1 for issue in closed if _has_label(issue, "result-profit"))
        lose_count = sum(1 for issue in closed if _has_label(issue, "result-loss"))
        stoploss_count = sum(
            1 for issue in closed if _has_label(issue, "result-stoploss-hit")
        )
        win_rate = round(win_count / closed_count, 2) if closed_count else 0.0

        performance[f"setup_{setup}"] = {
            "closed_count": closed_count,
            "win_count": win_count,
            "lose_count": lose_count,
            "stoploss_count": stoploss_count,
            "win_rate": win_rate,
        }

    return performance


def _compute_current_holdings(
    issues: list[dict[str, Any]], report_date: date
) -> dict[str, Any]:
    holdings: list[dict[str, Any]] = []
    by_setup = {"a": 0, "b": 0, "c": 0}

    for issue in issues:
        if not _has_label(issue, "holding"):
            continue

        setup = _determine_setup(issue)
        if setup:
            by_setup[setup] += 1

        entry_date = _parse_entry_date_from_body(issue)
        days_held = _compute_days_held(entry_date, report_date) if entry_date else None
        pnl_pct = _parse_pnl_from_comments(issue)

        holdings.append(
            {
                "issue_number": issue.get("number"),
                "title": issue.get("title", ""),
                "setup": setup,
                "days_held": days_held,
                "pnl_pct": pnl_pct if pnl_pct is not None else "N/A",
            }
        )

    return {
        "total": len(holdings),
        "by_setup": by_setup,
        "holdings": holdings,
    }


def _build_report(
    issues: list[dict[str, Any]],
    guardrail_triggered_count: int,
    report_date: date,
    iso_year: int,
    iso_week: int,
) -> dict[str, Any]:
    week_start, week_end = _week_boundaries_taiwan(iso_year, iso_week)

    return {
        "report_year": iso_year,
        "report_week": iso_week,
        "report_date": report_date.isoformat(),
        "generated_at": datetime.now(_TZ_TAIPEI).isoformat(),
        "system_health": _compute_system_health(
            issues, week_start, week_end, guardrail_triggered_count
        ),
        "strategy_performance": _compute_strategy_performance(issues),
        "current_holdings": _compute_current_holdings(issues, report_date),
    }


def _write_json_report(report: dict[str, Any], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def _format_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _write_html_report(report: dict[str, Any], output_path: str) -> None:
    health = report["system_health"]
    perf = report["strategy_performance"]
    holdings = report["current_holdings"]

    rows = []
    for setup, label in (("a", "Setup A"), ("b", "Setup B"), ("c", "Setup C")):
        data = perf[f"setup_{setup}"]
        rows.append(
            f"""
            <tr>
              <td>{label}</td>
              <td>{data["closed_count"]}</td>
              <td>{data["win_count"]}</td>
              <td>{data["lose_count"]}</td>
              <td>{data["stoploss_count"]}</td>
              <td>{_format_pct(data["win_rate"])}</td>
            </tr>
            """
        )

    holdings_items = []
    for h in holdings["holdings"]:
        pnl = h["pnl_pct"]
        if pnl != "N/A":
            try:
                pnl_value = float(pnl)
                css_class = "positive" if pnl_value >= 0 else "negative"
                pnl_display = f'<span class="{css_class}">{pnl_value:+.2f}%</span>'
            except ValueError:
                pnl_display = f"<span>{pnl}%</span>"
        else:
            pnl_display = "<span>N/A</span>"

        days_display = str(h["days_held"]) if h["days_held"] is not None else "N/A"
        holdings_items.append(
            f"""
            <li>
              <strong>#{h['issue_number']} {h['title']}</strong><br>
              進場天數：{days_display}｜目前損益：{pnl_display}
            </li>
            """
        )

    holdings_list_html = "\n".join(holdings_items) if holdings_items else "<li>目前無持倉</li>"

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TW Institutional Strategy Weekly Report</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --card: #ffffff;
      --text: #1f2328;
      --muted: #57606a;
      --border: #d0d7de;
      --accent: #0969da;
      --win: #1a7f37;
      --loss: #cf222e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
      padding: 16px;
    }}
    header {{
      margin-bottom: 24px;
    }}
    h1 {{
      font-size: 1.5rem;
      margin: 0 0 8px;
    }}
    .updated {{
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }}
    h2 {{
      font-size: 1.1rem;
      margin: 0 0 12px;
      color: var(--accent);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      text-align: left;
      padding: 8px;
      border-bottom: 1px solid var(--border);
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .metric-value {{ font-weight: 600; }}
    .holdings-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .holdings-list li {{
      padding: 10px 0;
      border-bottom: 1px solid var(--border);
    }}
    .holdings-list li:last-child {{ border-bottom: none; }}
    .disclaimer {{
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .positive {{ color: var(--win); }}
    .negative {{ color: var(--loss); }}
    .summary {{
      color: var(--muted);
      font-size: 0.95rem;
      margin-bottom: 12px;
    }}
    @media (max-width: 480px) {{
      h1 {{ font-size: 1.25rem; }}
      .card {{ padding: 12px; }}
      th, td {{ padding: 6px; font-size: 0.9rem; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>TW Institutional Strategy Weekly Report</h1>
      <div class="updated">
        最後更新時間：<time datetime="{report['generated_at']}">{report['generated_at']}</time>
      </div>
    </header>

    <section class="card">
      <h2>系統健康（當週）</h2>
      <table>
        <tbody>
          <tr>
            <th>新增候選 Issues</th>
            <td class="metric-value">{health['total_screened_this_week']} 個</td>
          </tr>
          <tr>
            <th>Audit 一次通過率</th>
            <td class="metric-value">{_format_pct(health['audit_pass_rate'])}</td>
          </tr>
          <tr>
            <th>Guardrail 攔截次數</th>
            <td class="metric-value">{health['guardrail_triggered_count']} 次</td>
          </tr>
          <tr>
            <th>人工介入次數</th>
            <td class="metric-value">{health['human_review_count']} 次</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>目前持倉</h2>
      <p class="summary">
        總計 {holdings['total']} 檔
        （Setup A：{holdings['by_setup']['a']}／Setup B：{holdings['by_setup']['b']}／Setup C：{holdings['by_setup']['c']}）
      </p>
      <ul class="holdings-list">
        {holdings_list_html}
      </ul>
    </section>

    <section class="card">
      <h2>歷史策略績效</h2>
      <table>
        <thead>
          <tr>
            <th>策略</th>
            <th>總筆數</th>
            <th>獲利</th>
            <th>虧損</th>
            <th>停損</th>
            <th>勝率</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </section>

    <section class="card disclaimer">
      免責聲明：本系統為個人研究工具，不構成投資建議。所有交易決策均需自行判斷，自負盈虧。
    </section>
  </div>
</body>
</html>
"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def main() -> int:
    report_date = _today_taiwan()
    iso_year, iso_week = _current_iso_week()
    week_start, week_end = _week_boundaries_taiwan(iso_year, iso_week)

    print(f"Generating report for ISO week {iso_year}-W{iso_week:02d} ({report_date})")

    issues = _list_all_issues()
    print(f"Loaded {len(issues)} issues")

    guardrail_artifacts = _this_week_guardrail_artifacts(week_start, week_end)
    print(f"Found {len(guardrail_artifacts)} guardrail artifacts this week")
    guardrail_triggered_count = _count_guardrail_triggers(
        guardrail_artifacts, week_start, week_end
    )

    report = _build_report(
        issues, guardrail_triggered_count, report_date, iso_year, iso_week
    )

    json_path = os.path.join(_REPORT_DIR, f"report_{iso_year}{iso_week:02d}.json")
    _write_json_report(report, json_path)
    print(f"OK: JSON report written to {json_path}")

    _write_html_report(report, _HTML_PATH)
    print(f"OK: HTML report written to {_HTML_PATH}")

    health = report["system_health"]
    print(
        f"screened={health['total_screened_this_week']}, "
        f"audit_pass_rate={health['audit_pass_rate']}, "
        f"guardrail_triggered={health['guardrail_triggered_count']}, "
        f"human_review={health['human_review_count']}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
