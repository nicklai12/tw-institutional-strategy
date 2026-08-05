"""Tests for scripts/data/fetch_institutional.py backfill behavior."""

import json
import os
from unittest.mock import patch

from tests.conftest import TEST_DATE_MONDAY, make_mock_get


def _raw_files(raw_dir: str) -> list[str]:
    return sorted(f for f in os.listdir(raw_dir) if f.endswith(".json"))


def test_fetch_single_day(fetch_module, tmp_path, monkeypatch, patch_module_today):
    """--backfill-days 0 fetches only today on a trading day."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", make_mock_get()
    ):
        exit_code = fetch_module.main(backfill_days=0)

    assert exit_code == 0
    assert _raw_files(str(raw_dir)) == ["20260803.json"]

    payload = json.loads((raw_dir / "20260803.json").read_text(encoding="utf-8"))
    assert payload["fetch_date"] == "2026-08-03"


def test_fetch_backfill_n_days(fetch_module, tmp_path, monkeypatch, patch_module_today):
    """--backfill-days 5 writes exactly 5 recent trading-day raw files."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", make_mock_get()
    ):
        exit_code = fetch_module.main(backfill_days=5)

    assert exit_code == 0
    assert _raw_files(str(raw_dir)) == [
        "20260728.json",
        "20260729.json",
        "20260730.json",
        "20260731.json",
        "20260803.json",
    ]


def test_fetch_idempotent(fetch_module, tmp_path, monkeypatch, patch_module_today):
    """Running the same backfill twice produces only one file per trading day."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", make_mock_get()
    ):
        assert fetch_module.main(backfill_days=1) == 0
        assert fetch_module.main(backfill_days=1) == 0

    assert _raw_files(str(raw_dir)) == ["20260803.json"]


def test_fetch_api_error_continues(
    fetch_module, tmp_path, monkeypatch, patch_module_today
):
    """A single-day API failure is skipped and backfill continues without failing."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    # 20260803 (today) fails; the loop continues to 20260731 and 20260730.
    mock_get = make_mock_get(fail_dates={"20260803"})

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", mock_get
    ):
        exit_code = fetch_module.main(backfill_days=2)

    assert exit_code == 0
    assert _raw_files(str(raw_dir)) == ["20260730.json", "20260731.json"]


def test_fetch_skips_weekend(fetch_module, tmp_path, monkeypatch, patch_module_today):
    """Backfill skips weekends and only writes weekday files."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", make_mock_get()
    ):
        exit_code = fetch_module.main(backfill_days=5)

    assert exit_code == 0
    files = _raw_files(str(raw_dir))
    assert len(files) == 5
    assert "20260802.json" not in files  # Sunday
    assert "20260801.json" not in files  # Saturday
    assert all(int(f.replace(".json", "")) not in {20260801, 20260802} for f in files)


def test_backfill_skips_date_when_twse_returns_empty_data(
    fetch_module, tmp_path, monkeypatch, patch_module_today
):
    """A date returning an empty TWSE array is skipped without failing backfill."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    mock_get = make_mock_get(response_by_date={"20260803": {"stat": "OK", "data": []}})

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", mock_get
    ):
        exit_code = fetch_module.main(backfill_days=1)

    assert exit_code == 0
    assert _raw_files(str(raw_dir)) == ["20260731.json"]


def test_backfill_skips_date_when_twse_returns_invalid_format(
    fetch_module, tmp_path, monkeypatch, patch_module_today
):
    """A date with a TWSE response missing required fields is skipped without failing."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    invalid_response = {
        "stat": "OK",
        "fields": ["證券名稱"],
        "data": [],
    }
    mock_get = make_mock_get(response_by_date={"20260803": invalid_response})

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", mock_get
    ):
        exit_code = fetch_module.main(backfill_days=1)

    assert exit_code == 0
    assert _raw_files(str(raw_dir)) == ["20260731.json"]


def test_backfill_continues_after_skip_and_returns_exit_code_0(
    fetch_module, tmp_path, monkeypatch, patch_module_today
):
    """Backfill continues fetching remaining days after skipping an invalid date."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))

    mock_get = make_mock_get(response_by_date={"20260803": {"stat": "OK", "data": []}})

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch.object(
        fetch_module.requests, "get", mock_get
    ):
        exit_code = fetch_module.main(backfill_days=2)

    assert exit_code == 0
    assert _raw_files(str(raw_dir)) == ["20260730.json", "20260731.json"]
