"""Tests for scripts/data/compute_rolling.py rolling-window behavior."""

import datetime
import json
import os
from functools import partial
from unittest.mock import patch

import pytest

from tests.conftest import build_raw_payload, write_raw_file


def _date_str_sequence(start: datetime.date, count: int) -> list[str]:
    """Return ISO date strings for a consecutive calendar-day sequence."""
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(count)]


def _write_raw_sequence(raw_dir: str, dates: list[str]) -> None:
    """Write one raw file per date with deterministic but varied content."""
    for idx, date_str in enumerate(dates):
        payload = build_raw_payload(date_str, record_count=101, ticker_offset=idx * 101)
        write_raw_file(raw_dir, date_str, payload)


def test_compute_with_exactly_20_days(rolling_module, tmp_path, monkeypatch):
    """With 20 raw files compute_rolling uses all 20 days."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))

    dates = _date_str_sequence(datetime.date(2026, 7, 1), 20)
    _write_raw_sequence(str(raw_dir), dates)

    result = rolling_module.compute_rolling(str(raw_dir))

    assert result["days_used"] == 20
    assert result["fetch_date"] == dates[-1]


def test_compute_with_more_than_20_days(rolling_module, tmp_path, monkeypatch):
    """With more than 20 raw files compute_rolling keeps only the latest 20."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))

    dates = _date_str_sequence(datetime.date(2026, 7, 1), 25)
    _write_raw_sequence(str(raw_dir), dates)

    result = rolling_module.compute_rolling(str(raw_dir))

    assert result["days_used"] == 20
    assert result["fetch_date"] == dates[-1]


def test_compute_with_less_than_20_days(rolling_module, tmp_path, monkeypatch):
    """With fewer than 20 raw files compute_rolling degrades without raising."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))

    dates = _date_str_sequence(datetime.date(2026, 7, 1), 5)
    _write_raw_sequence(str(raw_dir), dates)

    result = rolling_module.compute_rolling(str(raw_dir))

    assert result["days_used"] == 5
    assert result["fetch_date"] == dates[-1]


def test_compute_output_schema(rolling_module, tmp_path, monkeypatch):
    """Rolling output contains the canonical top-level and record-level schema."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))

    dates = _date_str_sequence(datetime.date(2026, 7, 1), 20)
    _write_raw_sequence(str(raw_dir), dates)

    result = rolling_module.compute_rolling(str(raw_dir))

    # Top-level keys (oracle raw-file schema plus rolling-specific additions).
    assert set(result.keys()) == {
        "fetch_date",
        "fetch_timestamp",
        "source_url",
        "record_count",
        "days_used",
        "data",
    }
    assert result["days_used"] == 20
    assert isinstance(result["record_count"], int)
    assert result["record_count"] == len(result["data"])

    # Record-level keys.
    required_record_keys = {
        "ticker",
        "name",
        "foreign_buy",
        "foreign_sell",
        "foreign_net",
        "trust_buy",
        "trust_sell",
        "trust_net",
        "dealer_net",
        "foreign_5d_net",
        "trust_5d_net",
        "trust_10d_net",
        "trust_10d_buy_days",
        "foreign_10d_net",
        "foreign_20d_net",
        "foreign_recent_3d_all_buy",
    }
    for record in result["data"]:
        assert set(record.keys()) == required_record_keys


def test_compute_no_raw_files_raises(rolling_module, tmp_path, monkeypatch):
    """With zero raw files compute_rolling raises an exception."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))
    os.makedirs(str(raw_dir), exist_ok=True)

    with pytest.raises(Exception):
        rolling_module.compute_rolling(str(raw_dir))


def test_rolling_filename_matches_latest_raw_date(
    rolling_module, tmp_path, monkeypatch, patch_module_today
):
    """Rolling output file is named after the latest raw date, not runner today."""
    raw_dir = tmp_path / "raw"
    rolling_dir = tmp_path / "rolling"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))
    monkeypatch.setattr(rolling_module, "_ROLLING_DIR", str(rolling_dir))

    dates = _date_str_sequence(datetime.date(2026, 7, 1), 20)
    _write_raw_sequence(str(raw_dir), dates)

    # main() calls compute_rolling() with no args, so wrap it to use our temp raw_dir.
    monkeypatch.setattr(
        rolling_module,
        "compute_rolling",
        partial(rolling_module.compute_rolling, raw_dir=str(raw_dir)),
    )

    # main() no longer uses runner today for the filename; it uses the latest
    # raw date, so patching datetime is unnecessary.
    exit_code = rolling_module.main()

    assert exit_code == 0
    expected_path = rolling_dir / "20260720_rolling.json"
    assert expected_path.exists()
    payload = json.loads(expected_path.read_text(encoding="utf-8"))
    assert payload["fetch_date"] == "2026-07-20"
