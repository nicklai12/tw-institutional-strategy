"""Oracle comparison tests for Setup C screener."""

import glob
import json

import pytest

from scripts.screener.setup_c import screen_setup_c


def get_oracle_pairs():
    """Collect Setup C oracle input/output fixture pairs (v2 naming)."""
    inputs = sorted(glob.glob("tests/fixtures/oracle_input_c_????-??-??.json"))
    pairs = []
    for inp in inputs:
        out = inp.replace("oracle_input_c_", "oracle_output_c_")
        pairs.append((inp, out))
    return pairs


def _mock_price_fetcher(stocks: list[dict]):
    """Return a price fetcher that serves close from the oracle stock dicts."""
    by_ticker = {s["ticker"]: s for s in stocks if s.get("ticker")}

    def fetcher(ticker: str, date: str) -> dict | None:
        stock = by_ticker.get(ticker)
        if stock is None:
            return None
        return {
            "close": stock.get("close", 0),
        }

    return fetcher


@pytest.mark.parametrize("input_path,output_path", get_oracle_pairs())
def test_setup_c_matches_oracle(input_path: str, output_path: str):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    screen_date = oracle_input["date"]
    market_cap_threshold_b = oracle_input.get("market_cap_threshold_b", 1000)

    # Use the artifact_run_id recorded in the oracle output so the candidate
    # fields match exactly.
    candidates_out = oracle_output.get("setup_c_candidates", [])
    artifact_run_id = (
        candidates_out[0]["artifact_run_id"]
        if candidates_out
        else "manual"
    )

    all_results = screen_setup_c(
        oracle_input["stocks"],
        price_fetcher=_mock_price_fetcher(oracle_input["stocks"]),
        screen_date=screen_date,
        market_cap_threshold_b=market_cap_threshold_b,
        artifact_run_id=artifact_run_id,
    )

    assert all_results["screen_date"] == oracle_output["date"]
    assert all_results["setup_c_candidates"] == candidates_out
    assert all_results["excluded"] == oracle_output.get("excluded", [])
