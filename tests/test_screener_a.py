"""Oracle comparison tests for Setup A screener."""

import glob
import json

import pytest

from scripts.screener.setup_a import screen_setup_a


def get_oracle_pairs():
    inputs = sorted(glob.glob("tests/fixtures/oracle_input_*.json"))
    pairs = []
    for inp in inputs:
        out = inp.replace("oracle_input_", "oracle_output_")
        pairs.append((inp, out))
    return pairs


def _mock_price_fetcher(stock: dict):
    """Return a price fetcher that serves metrics from the oracle stock dict."""

    def fetcher(ticker: str, date: str) -> dict | None:
        if stock.get("ticker") != ticker:
            return None
        return {
            "close": stock.get("close", 0),
            "ma5": stock.get("close", 0),  # not used for selection
            "ma20": stock.get("ma20", 0),
            "ma20_direction": stock.get("ma20_direction", ""),
            "avg_volume_20d": stock.get("avg_volume_20d", 0),
        }

    return fetcher


@pytest.mark.parametrize("input_path,output_path", get_oracle_pairs())
def test_setup_a_matches_oracle(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    screen_date = oracle_input["date"]
    all_results: list[dict] = []

    # Screen each stock independently so the mock fetcher can serve its metrics.
    for stock in oracle_input["stocks"]:
        result = screen_setup_a(
            [stock],
            price_fetcher=_mock_price_fetcher(stock),
            screen_date=screen_date,
            min_avg_volume_m=200,  # match Phase 1 oracle threshold (200,000 千元)
            max_candidates=100,    # disable cap for oracle comparison
            allowed_directions={"rising"},
        )
        all_results.extend(result)

    result_tickers = {r["ticker"] for r in all_results}
    expected_tickers = {c["ticker"] for c in oracle_output["setup_a_candidates"]}

    if result_tickers != expected_tickers:
        missing = expected_tickers - result_tickers
        extra = result_tickers - expected_tickers
        diff_parts = []
        if missing:
            diff_parts.append(f"missing: {sorted(missing)}")
        if extra:
            diff_parts.append(f"extra: {sorted(extra)}")
        raise AssertionError(
            f"日期 {screen_date} 篩選結果不符\n"
            f"預期: {sorted(expected_tickers)}\n"
            f"實際: {sorted(result_tickers)}\n"
            f"diff: {'; '.join(diff_parts)}"
        )
