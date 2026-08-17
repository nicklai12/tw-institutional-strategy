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


def _write_rolling_oracle_raw_files(raw_dir: str, oracle_input: dict) -> list[str]:
    """Materialize a rolling oracle fixture's ``daily_history`` into raw files.

    The ``daily_history`` arrays are ordered oldest-to-newest, ending at
    ``oracle_input["fetch_date"]``.  One raw file is written per calendar day.
    """
    latest_date = datetime.date.fromisoformat(oracle_input["fetch_date"])
    history = oracle_input.get("daily_history", {})
    if not history:
        return []

    sample_ticker = next(iter(history))
    days = len(history[sample_ticker]["foreign_net"])
    dates = [
        (latest_date - datetime.timedelta(days=days - 1 - i)).isoformat()
        for i in range(days)
    ]
    name_by_ticker = {r["ticker"]: r["name"] for r in oracle_input["data"]}

    for idx, date_str in enumerate(dates):
        payload = {
            "fetch_date": date_str,
            "fetch_timestamp": oracle_input.get(
                "fetch_timestamp", "2026-01-01T00:00:00"
            ),
            "source_url": oracle_input.get("source_url", ""),
            "record_count": len(history),
            "data": [
                {
                    "ticker": ticker,
                    "name": name_by_ticker.get(ticker, ticker),
                    "foreign_buy": 0,
                    "foreign_sell": 0,
                    "foreign_net": vals["foreign_net"][idx],
                    "trust_buy": 0,
                    "trust_sell": 0,
                    "trust_net": vals["trust_net"][idx],
                    "dealer_net": 0,
                }
                for ticker, vals in history.items()
            ],
        }
        write_raw_file(raw_dir, date_str, payload)

    return dates


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
        "foreign_buy_streak_day",
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


@pytest.mark.parametrize(
    "input_file,output_file",
    [
        (
            "oracle_rolling_bc_input_2026-08-01.json",
            "oracle_rolling_bc_output_2026-08-01.json",
        ),
        (
            "oracle_rolling_bc_input_2026-08-02.json",
            "oracle_rolling_bc_output_2026-08-02.json",
        ),
    ],
)
def test_rolling_bc_oracle(
    rolling_module, tmp_path, monkeypatch, input_file, output_file
):
    """compute_rolling output matches the Setup B/C oracle fixtures exactly."""
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))

    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(os.path.join(fixtures_dir, input_file), encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(os.path.join(fixtures_dir, output_file), encoding="utf-8") as f:
        expected = json.load(f)

    _write_rolling_oracle_raw_files(str(raw_dir), oracle_input)
    result = rolling_module.compute_rolling(str(raw_dir))

    assert result == expected
