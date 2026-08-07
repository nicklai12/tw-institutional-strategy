"""Tests for create_issues.py."""

from unittest.mock import patch

from scripts.screener.create_issues import create_issue


_CANDIDATE = {
    "ticker": "2330",
    "name": "台積電",
    "screen_date": "2026-07-28",
    "avg_volume_20d_m": 1000,
    "foreign_5d_net": 100,
    "trust_5d_net": 200,
    "close": 510.0,
    "ma20": 500.0,
    "ma20_direction": "上升",
    "entry_zone": "500-505",
    "stop_loss_price": 480.0,
}


@patch("scripts.screener.create_issues._issue_exists", return_value=False)
@patch("scripts.screener.create_issues._run_gh")
def test_create_issues_normal_label_includes_screened_not_auto_ok(mock_gh, mock_exists):
    """Creating an issue labels it setup-a and screened, but not auto-ok."""
    mock_gh.return_value.returncode = 0
    mock_gh.return_value.stdout = "https://github.com/owner/repo/issues/42\n"

    number = create_issue(_CANDIDATE, project_number=None)
    assert number == 42

    args = mock_gh.call_args[0][0]
    label_index = args.index("--label") + 1
    labels = args[label_index]
    assert "setup-a" in labels
    assert "screened" in labels
    assert "auto-ok" not in labels


@patch("scripts.screener.create_issues._issue_exists", return_value=False)
@patch("scripts.screener.create_issues._run_gh")
def test_create_issues_regression_auto_ok_not_present(mock_gh, mock_exists):
    """Regression guard: auto-ok must never appear in the initial labels."""
    mock_gh.return_value.returncode = 0
    mock_gh.return_value.stdout = "https://github.com/owner/repo/issues/43\n"

    create_issue(_CANDIDATE, project_number=None)

    args = mock_gh.call_args[0][0]
    label_index = args.index("--label") + 1
    labels = args[label_index]
    assert "auto-ok" not in labels
    assert "screened" in labels
