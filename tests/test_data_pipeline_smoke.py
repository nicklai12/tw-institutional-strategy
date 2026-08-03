"""End-to-end smoke test for the data fetch + compute pipeline."""

import glob
import json
import os
from functools import partial
from unittest.mock import patch

from tests.conftest import TEST_DATE_MONDAY, make_mock_get


def test_full_pipeline_smoke(
    fetch_module,
    rolling_module,
    tmp_path,
    monkeypatch,
    patch_module_today,
    capsys,
):
    """A full pipeline run with mocked TWSE API produces 20 raw files and valid rolling output."""
    raw_dir = tmp_path / "raw"
    rolling_dir = tmp_path / "rolling"
    monkeypatch.setattr(fetch_module, "_RAW_OUTPUT_DIR", str(raw_dir))
    monkeypatch.setattr(rolling_module, "_RAW_DIR", str(raw_dir))
    monkeypatch.setattr(rolling_module, "_ROLLING_DIR", str(rolling_dir))

    # compute_rolling.main() calls compute_rolling() with no args, so its default
    # raw_dir (captured at import time) must be overridden via a partial.
    monkeypatch.setattr(
        rolling_module,
        "compute_rolling",
        partial(rolling_module.compute_rolling, raw_dir=str(raw_dir)),
    )

    with patch_module_today(fetch_module, TEST_DATE_MONDAY), patch_module_today(
        rolling_module, TEST_DATE_MONDAY
    ), patch.object(fetch_module.requests, "get", make_mock_get()):
        fetch_exit = fetch_module.main(backfill_days=20)
        assert fetch_exit == 0

        raw_files = sorted(glob.glob(os.path.join(str(raw_dir), "*.json")))
        assert len(raw_files) == 20

        compute_exit = rolling_module.main()
        assert compute_exit == 0

    rolling_files = sorted(glob.glob(os.path.join(str(rolling_dir), "*_rolling.json")))
    assert len(rolling_files) == 1

    with open(rolling_files[0], encoding="utf-8") as f:
        result = json.load(f)
    assert result["days_used"] == 20

    captured = capsys.readouterr()
    assert "WARNING: 原始檔案不足" not in captured.out
    assert "WARNING: 原始檔案不足" not in captured.err
