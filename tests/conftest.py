"""Shared helpers for the data pipeline tests."""

import datetime
import json
import os
from unittest.mock import MagicMock, patch

import pytest

import scripts.data.compute_rolling as rolling_mod
import scripts.data.fetch_institutional as fetch_mod


# Fixed test dates (known weekdays).
TEST_DATE_MONDAY = datetime.date(2026, 8, 3)
TEST_DATE_FRIDAY = datetime.date(2026, 7, 31)


def fake_datetime_module(fixed_date: datetime.date):
    """Return a fake ``datetime`` module with ``date.today()`` pinned to ``fixed_date``.

    The fake module delegates ``datetime`` and ``timedelta`` to the real module so
    that existing code using those names continues to work.
    """

    class FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return fixed_date

    class FakeModule:
        pass

    fake = FakeModule()
    fake.date = FixedDate
    fake.datetime = datetime.datetime
    fake.timedelta = datetime.timedelta
    return fake


def make_twse_response(record_count: int = 101, ticker_offset: int = 0) -> dict:
    """Return a realistic TWSE T86 response dict with the required fields."""
    fields = [
        "證券代號",
        "證券名稱",
        "外陸資買進股數(不含外資自營商)",
        "外陸資賣出股數(不含外資自營商)",
        "投信買進股數",
        "投信賣出股數",
        "自營商買賣超股數",
    ]
    rows = []
    for i in range(record_count):
        seq = ticker_offset + i + 1
        ticker = f"{seq:04d}"
        rows.append(
            [
                ticker,
                f"Stock {ticker}",
                f"{(i + 1) * 1000:,}",
                f"{(i + 1) * 500:,}",
                f"{(i + 1) * 2000:,}",
                f"{(i + 1) * 1000:,}",
                f"{(i + 1) * 300:,}",
            ]
        )
    return {"stat": "OK", "fields": fields, "data": rows}


def build_raw_payload(
    date_str: str, record_count: int = 101, ticker_offset: int = 0
) -> dict:
    """Build a canonical raw payload using the real parser and a mock TWSE response."""
    compact = date_str.replace("-", "")
    source_url = (
        f"https://www.twse.com.tw/rwd/zh/fund/T86?date={compact}&selectType=ALLBUT0999"
    )
    response = make_twse_response(record_count, ticker_offset)
    return fetch_mod.parse_institutional_response(
        response,
        fetch_date=date_str,
        source_url=source_url,
        fetch_timestamp="2026-01-01T00:00:00",
    )


def write_raw_file(raw_dir: str, date_str: str, payload: dict) -> None:
    """Write a canonical raw payload to raw_dir/YYYYMMDD.json."""
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, f"{date_str.replace('-', '')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def make_mock_get(
    response_by_date: dict[str, dict] | None = None,
    fail_dates: set[str] | None = None,
    default_response: dict | None = None,
) -> callable:
    """Factory for a mock ``requests.get`` that can vary by date or fail dates.

    Args:
        response_by_date: Map of YYYYMMDD -> TWSE response dict.
        fail_dates: Set of YYYYMMDD strings that should trigger an HTTPError.
        default_response: Response dict used when a date is not in response_by_date
            and not in fail_dates.
    """
    from urllib.parse import parse_qs, urlparse

    from requests import HTTPError

    response_by_date = response_by_date or {}
    fail_dates = fail_dates or set()
    if default_response is None:
        default_response = make_twse_response()

    def _get(url: str, *args, **kwargs):
        qs = parse_qs(urlparse(url).query)
        compact = qs.get("date", [""])[0]

        if compact in fail_dates:
            mock = MagicMock()
            mock.raise_for_status.side_effect = HTTPError(
                f"Mock API failure for {compact}"
            )
            return mock

        response_data = response_by_date.get(compact, default_response)
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = response_data
        mock.raise_for_status.return_value = None
        return mock

    return _get


@pytest.fixture
def fetch_module():
    """Provide the fetch_institutional module under test."""
    return fetch_mod


@pytest.fixture
def rolling_module():
    """Provide the compute_rolling module under test."""
    return rolling_mod


@pytest.fixture
def patch_module_today():
    """Patch ``datetime.date.today`` inside a target module to a fixed date."""

    def _patch(module, date: datetime.date):
        return patch.object(module, "datetime", fake_datetime_module(date))

    return _patch
