import glob
import json

import pytest

from src.filter import filter_setup_a


def get_oracle_pairs():
    """Collect Setup A oracle input/output fixture pairs."""
    inputs = sorted(glob.glob("tests/fixtures/oracle_input_????-??-??.json"))
    pairs = []
    for inp in inputs:
        out = inp.replace("oracle_input_", "oracle_output_")
        pairs.append((inp, out))
    return pairs


@pytest.mark.parametrize("input_path,output_path", get_oracle_pairs())
def test_setup_a_matches_oracle(input_path, output_path):
    with open(input_path, encoding="utf-8") as f:
        oracle_input = json.load(f)
    with open(output_path, encoding="utf-8") as f:
        oracle_output = json.load(f)

    result = filter_setup_a(oracle_input["stocks"])
    result_tickers = {r["ticker"] for r in result}
    expected_tickers = {c["ticker"] for c in oracle_output["setup_a_candidates"]}

    assert result_tickers == expected_tickers, (
        f"日期 {oracle_input['date']} 篩選結果不符\n"
        f"預期: {expected_tickers}\n實際: {result_tickers}"
    )
