"""Tests for the Audit action."""

from unittest.mock import patch

import pytest

from scripts.audit.audit_issue import (
    _determine_setup,
    _parse_field,
    _validate_field,
    audit_issue,
)


def _make_issue(body: str, labels: list[str], title: str = "") -> dict:
    return {
        "body": body,
        "labels": [{"name": name} for name in labels],
        "title": title,
    }


def test_parse_field():
    body = "- **ticker**: 2330\n- **risk_r_pct**: 0.8"
    assert _parse_field(body, "ticker") == "2330"
    assert _parse_field(body, "risk_r_pct") == "0.8"
    assert _parse_field(body, "missing") is None


def test_determine_setup_from_labels():
    issue = _make_issue("", ["setup-b", "screened"])
    assert _determine_setup(issue) == "b"


def test_determine_setup_from_title():
    issue = _make_issue("", [], "[Setup-C][20260727] 2317 鴻海")
    assert _determine_setup(issue) == "c"


def test_validate_field_missing():
    assert _validate_field("ticker", None, "a") == "欄位不存在"


def test_validate_field_empty():
    assert _validate_field("ticker", "", "a") == "欄位為空"


def test_validate_field_placeholder():
    assert _validate_field("entry_zone", "⚠️ 待人工填寫", "a") == "仍為待人工填寫的佔位符"


def test_validate_field_position_size_lots_numeric():
    assert _validate_field("position_size_lots", "5", "a") is None
    assert _validate_field("position_size_lots", "abc", "a") == "必須為數字，目前為：abc"


def test_validate_field_risk_r_pct_over_limit():
    assert _validate_field("risk_r_pct", "1.5", "a") == "risk_r_pct 不得超過 1.0%，目前為：1.5"


def test_validate_field_artifact_run_id_non_numeric():
    assert _validate_field("artifact_run_id", "abc", "a") == "必須為數字格式，目前為：abc"


@patch("scripts.audit.audit_issue._get_issue")
@patch("scripts.audit.audit_issue._add_comment")
@patch("scripts.audit.audit_issue._add_label")
@patch("scripts.audit.audit_issue._remove_label")
@patch("scripts.audit.audit_issue._has_label")
def test_audit_issue_passes(
    mock_has_label, mock_remove, mock_add, mock_comment, mock_get_issue
):
    mock_has_label.return_value = True  # data-missing exists, should be removed
    mock_get_issue.return_value = _make_issue(
        body=(
            "- **ticker**: 2330\n"
            "- **screen_date**: 2026-07-27\n"
            "- **avg_volume_20d_m**: 600\n"
            "- **foreign_5d_net**: 1000\n"
            "- **trust_5d_net**: 500\n"
            "- **close_vs_ma20**: above\n"
            "- **ma20_direction**: rising\n"
            "- **entry_zone**: 500-510\n"
            "- **stop_loss_price**: 465\n"
            "- **position_size_lots**: 2\n"
            "- **risk_r_pct**: 0.8\n"
            "- **artifact_run_id**: 12345"
        ),
        labels=["setup-a"],
    )

    result = audit_issue(1)
    assert result["passed"] is True
    assert result["setup"] == "a"

    mock_remove.assert_called_once_with(1, "data-missing")
    mock_add.assert_not_called()


@patch("scripts.audit.audit_issue._get_issue")
@patch("scripts.audit.audit_issue._add_comment")
@patch("scripts.audit.audit_issue._add_label")
@patch("scripts.audit.audit_issue._remove_label")
@patch("scripts.audit.audit_issue._has_label")
def test_audit_issue_fails_missing_field_and_risk(
    mock_has_label, mock_remove, mock_add, mock_comment, mock_get_issue
):
    mock_has_label.return_value = True
    mock_get_issue.return_value = _make_issue(
        body=(
            "- **ticker**: 2330\n"
            "- **screen_date**: 2026-07-27\n"
            "- **risk_r_pct**: 1.5"
        ),
        labels=["setup-a"],
    )

    result = audit_issue(2)
    assert result["passed"] is False
    assert result["setup"] == "a"

    fields = {err["field"] for err in result["errors"]}
    assert "risk_r_pct" in fields
    assert "avg_volume_20d_m" in fields

    mock_add.assert_called_once_with(2, "data-missing")
    mock_remove.assert_called_once_with(2, "auto-ok")
