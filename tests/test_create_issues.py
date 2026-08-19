"""Tests for create_issues.py."""

from unittest.mock import patch

from scripts.screener.create_issues import (
    _SETUP_CONFIG,
    create_issue,
    detect_setup,
    get_candidates,
)


_CANDIDATE_A = {
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

_CANDIDATE_B = {
    "ticker": "B101",
    "name": "SetupB-Pass",
    "screen_date": "2026-08-02",
    "avg_volume_20d_m": 100,
    "trust_10d_net": 1000,
    "trust_10d_buy_days": 8,
    "foreign_10d_direction": "buying",
    "close_vs_ma20": "above",
    "breakout_price": 95,
    "breakout_date": "2026-08-02",
    "breakout_volume_m": 120,
    "entry_zone": "突破價 95.00 之上且量縮",
    "stop_loss_price": 93,
    "artifact_run_id": "23456",
}

_CANDIDATE_C = {
    "ticker": "C101",
    "name": "SetupC-Pass",
    "screen_date": "2026-08-02",
    "market_cap_b": 2000,
    "foreign_20d_net": -1350,
    "foreign_recent_3d": True,
    "foreign_buy_streak_day": 3,
    "price_bottom_status": "higher_lows",
    "entry_day": 3,
    "entry_zone": "外資連買第 3 天當日價格區間（由 signal monitor 於進場日動態確認）",
    "stop_loss_price": 95,
    "artifact_run_id": "23456",
}


@patch("scripts.screener.create_issues._issue_exists", return_value=False)
@patch("scripts.screener.create_issues._run_gh")
def test_create_issues_normal_label_includes_screened_not_auto_ok(mock_gh, mock_exists):
    """Creating an issue labels it setup-a and screened, but not auto-ok."""
    mock_gh.return_value.returncode = 0
    mock_gh.return_value.stdout = "https://github.com/owner/repo/issues/42\n"

    number = create_issue(_CANDIDATE_A, project_number=None)
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

    create_issue(_CANDIDATE_A, project_number=None)

    args = mock_gh.call_args[0][0]
    label_index = args.index("--label") + 1
    labels = args[label_index]
    assert "auto-ok" not in labels
    assert "screened" in labels


@patch("scripts.screener.create_issues._issue_exists", return_value=False)
@patch("scripts.screener.create_issues._run_gh")
def test_create_setup_b_issue_uses_setup_b_labels_and_body(mock_gh, mock_exists):
    """Setup B candidate creates a Setup-B issue with the correct fields."""
    mock_gh.return_value.returncode = 0
    mock_gh.return_value.stdout = "https://github.com/owner/repo/issues/44\n"

    number = create_issue(_CANDIDATE_B, project_number=None, setup="b")
    assert number == 44

    args = mock_gh.call_args[0][0]
    title_index = args.index("--title") + 1
    label_index = args.index("--label") + 1
    body_index = args.index("--body") + 1

    assert args[title_index] == "[Setup-B][20260802] B101 SetupB-Pass"
    labels = args[label_index]
    assert "setup-b" in labels
    assert "screened" in labels
    assert "auto-ok" not in labels

    body = args[body_index]
    assert "## Setup B 候選股登記" in body
    assert "- **trust_10d_net**: 1000" in body
    assert "- **breakout_price**: 95" in body
    assert "- **foreign_10d_direction**: buying" in body


@patch("scripts.screener.create_issues._issue_exists", return_value=False)
@patch("scripts.screener.create_issues._run_gh")
def test_create_setup_c_issue_uses_setup_c_labels_and_body(mock_gh, mock_exists):
    """Setup C candidate creates a Setup-C issue with the correct fields."""
    mock_gh.return_value.returncode = 0
    mock_gh.return_value.stdout = "https://github.com/owner/repo/issues/45\n"

    number = create_issue(_CANDIDATE_C, project_number=None, setup="c")
    assert number == 45

    args = mock_gh.call_args[0][0]
    title_index = args.index("--title") + 1
    label_index = args.index("--label") + 1
    body_index = args.index("--body") + 1

    assert args[title_index] == "[Setup-C][20260802] C101 SetupC-Pass"
    labels = args[label_index]
    assert "setup-c" in labels
    assert "screened" in labels
    assert "auto-ok" not in labels

    body = args[body_index]
    assert "## Setup C 候選股登記" in body
    assert "- **market_cap_b**: 2000" in body
    assert "- **foreign_20d_net**: -1350" in body
    assert "- **entry_day**: 3" in body


def test_detect_setup_from_filename():
    """Filename is the primary source of truth for setup detection."""
    assert detect_setup("data/screener/screener_result_a_20260802.json", {}) == "a"
    assert detect_setup("data/screener/screener_result_b_20260802.json", {}) == "b"
    assert detect_setup("data/screener/screener_result_c_20260802.json", {}) == "c"


def test_detect_setup_from_payload_keys():
    """Payload keys are used as fallback when filename is ambiguous."""
    assert detect_setup("result.json", {"candidates": []}) == "a"
    assert detect_setup("result.json", {"setup_b_candidates": []}) == "b"
    assert detect_setup("result.json", {"setup_c_candidates": []}) == "c"


def test_detect_setup_filename_wins_over_payload():
    """Filename takes precedence over payload keys."""
    assert detect_setup("screener_result_b_20260802.json", {"candidates": []}) == "b"


def test_detect_setup_unknown_raises():
    """Unknown filename and payload should raise ValueError."""
    try:
        detect_setup("unknown.json", {"other": []})
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_get_candidates_per_setup():
    """Candidate list is extracted from the setup-specific payload key."""
    payload = {
        "candidates": [{"ticker": "A"}],
        "setup_b_candidates": [{"ticker": "B"}],
        "setup_c_candidates": [{"ticker": "C"}],
    }
    assert get_candidates(payload, "a") == [{"ticker": "A"}]
    assert get_candidates(payload, "b") == [{"ticker": "B"}]
    assert get_candidates(payload, "c") == [{"ticker": "C"}]


def test_setup_config_covers_all_setups():
    """Registry covers Setup A/B/C with distinct labels and keys."""
    assert set(_SETUP_CONFIG.keys()) == {"a", "b", "c"}
    assert _SETUP_CONFIG["a"]["label"] == "setup-a,screened"
    assert _SETUP_CONFIG["b"]["label"] == "setup-b,screened"
    assert _SETUP_CONFIG["c"]["label"] == "setup-c,screened"
