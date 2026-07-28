"""Schema validation tests for the fetch_institutional parser."""

import glob
import json
import os

import pytest

from scripts.data.fetch_institutional import parse_institutional_response


REQUIRED_TOP_KEYS = {
    "fetch_date",
    "fetch_timestamp",
    "source_url",
    "record_count",
    "data",
}

REQUIRED_RECORD_KEYS = {
    "ticker",
    "name",
    "foreign_buy",
    "foreign_sell",
    "foreign_net",
    "trust_buy",
    "trust_sell",
    "trust_net",
    "dealer_net",
}


def _build_mock_twse_response(oracle_input: dict) -> dict:
    """Build a realistic TWSE T86 response from an oracle_input fixture.

    Values are synthetic; the test only verifies schema and arithmetic.
    """
    fields = [
        "證券代號",
        "證券名稱",
        "外陸資買進股數(不含外資自營商)",
        "外陸資賣出股數(不含外資自營商)",
        "外陸資買賣超股數(不含外資自營商)",
        "外資自營商買進股數",
        "外資自營商賣出股數",
        "外資自營商買賣超股數",
        "投信買進股數",
        "投信賣出股數",
        "投信買賣超股數",
        "自營商買賣超股數",
        "自營商買進股數(自行買賣)",
        "自營商賣出股數(自行買賣)",
        "自營商買賣超股數(自行買賣)",
        "自營商買進股數(避險)",
        "自營商賣出股數(避險)",
        "自營商買賣超股數(避險)",
        "三大法人買賣超股數",
    ]

    # Distribute each stock's 5-day net into 5 identical daily values so the
    # parser output is deterministic. 1 lot = 1000 shares.
    rows = []
    for stock in oracle_input.get("stocks", []):
        foreign_daily = round(stock.get("foreign_5d_net", 0) / 5)
        trust_daily = round(stock.get("trust_5d_net", 0) / 5)
        dealer_daily = round((foreign_daily + trust_daily) / 10)

        foreign_buy_shares = max(foreign_daily, 0) * 1000
        foreign_sell_shares = max(-foreign_daily, 0) * 1000
        trust_buy_shares = max(trust_daily, 0) * 1000
        trust_sell_shares = max(-trust_daily, 0) * 1000
        dealer_net_shares = dealer_daily * 1000

        rows.append(
            [
                stock["ticker"],
                stock["name"],
                f"{foreign_buy_shares:,}",
                f"{foreign_sell_shares:,}",
                f"{foreign_daily * 1000:,}",
                "0",
                "0",
                "0",
                f"{trust_buy_shares:,}",
                f"{trust_sell_shares:,}",
                f"{trust_daily * 1000:,}",
                f"{dealer_net_shares:,}",
                "0",
                "0",
                "0",
                f"{dealer_net_shares:,}",
                "0",
                f"{dealer_net_shares:,}",
                f"{(foreign_daily + trust_daily + dealer_daily) * 1000:,}",
            ]
        )

    return {"stat": "OK", "fields": fields, "data": rows}


def get_oracle_inputs():
    return sorted(glob.glob("tests/fixtures/oracle_input_*.json"))


@pytest.mark.parametrize("input_path", get_oracle_inputs())
def test_parse_institutional_response_schema_and_math(input_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)

    mock_response = _build_mock_twse_response(oracle_input)
    fetch_date = oracle_input["date"]
    source_url = (
        f"https://www.twse.com.tw/rwd/zh/fund/T86?date="
        f"{fetch_date.replace('-', '')}&selectType=ALLBUT0999"
    )

    result = parse_institutional_response(
        mock_response,
        fetch_date=fetch_date,
        source_url=source_url,
        fetch_timestamp="2026-01-01T00:00:00",
    )

    # Top-level schema.
    assert set(result.keys()) == REQUIRED_TOP_KEYS
    assert result["fetch_date"] == fetch_date
    assert result["source_url"] == source_url
    assert isinstance(result["record_count"], int)
    assert result["record_count"] == len(result["data"])

    # Record-level schema and arithmetic.
    for record in result["data"]:
        assert set(record.keys()) == REQUIRED_RECORD_KEYS
        assert isinstance(record["ticker"], str)
        assert isinstance(record["name"], str)
        for key in REQUIRED_RECORD_KEYS - {"ticker", "name"}:
            assert isinstance(record[key], int)

        assert record["foreign_net"] == record["foreign_buy"] - record["foreign_sell"]
        assert record["trust_net"] == record["trust_buy"] - record["trust_sell"]

    # Each oracle ticker appears exactly once in the output.
    result_tickers = {r["ticker"] for r in result["data"]}
    expected_tickers = {s["ticker"] for s in oracle_input["stocks"]}
    assert result_tickers == expected_tickers
