# Stage 3A Diff 摘要：fetch_institutional.py

## 修改目標

根據 Stage 2 技術規格書（`reports/design_spec_20260731.json`）的 `design_decision_a`，修改 `scripts/data/fetch_institutional.py`，使其支援 `--backfill-days N` 參數，可補抓最近 N 個交易日的機構籌碼資料。

---

## 變更表格

| 區域 | 變更 | 原因 |
|---|---|---|
| 匯入 | `+import argparse` | 新增 CLI 參數解析 |
| 新增 `_write_raw_file()` | 抽出「寫入單日 raw JSON」邏輯 | 單日模式與 backfill 模式共用，避免重複 |
| 新增 `_backfill_trading_days()` | 由近到遠走訪交易日，直到累積 N 個成功或已存在 | 實作 `--backfill-days` 核心邏輯 |
| `main()` | 改為 `main(backfill_days: int = 0)`，N>0 時走 backfill 分支 | 保留預設單日行為，backfill 透過參數觸發 |
| `__main__` | 改為 argparse 解析 `--backfill-days` 後呼叫 `main()` | 提供 CLI 介面，同時讓測試可直接呼叫 `main()` |

---

## 冪等性與錯誤容忍設計

- **檔案已存在即跳過**：透過 `os.path.exists(output_path)` 檢查，若 `data/raw/YYYYMMDD.json` 已存在則印出 `SKIP` 並計入已存在天數，避免重複寫入。
- **API 失敗不中斷**：`fetch_institutional()` 抛出的任何 `RuntimeError`（包含 `TOO_FEW_RECORDS` 與 `API_CONNECTION_FAILED`）都被捕獲為 `WARNING` 並繼續下一日。
- **非交易日跳過**：週末透過既有 `is_trading_day()` 跳過；國定假日因 TWSE API 回傳過少紀錄，同樣被 `TOO_FEW_RECORDS` 捕獲並跳過，繼續往前補齊交易日。
- **計數邏輯**：迴圈停止條件為 `success_count + skipped_count < backfill_days`，確保最終取得（或已存在）指定數量的交易日資料。

---

## 驗收指令

```bash
# 在本地執行這個指令，應看到 data/raw/ 下出現 20 個 JSON 檔案
python scripts/data/fetch_institutional.py --backfill-days 20
ls data/raw/ | wc -l  # 預期輸出：>= 20
```

---

## 注意事項

- 未修改 `compute_rolling.py`。
- 未修改任何 `.github/workflows/` YAML 檔案。
- 未修改 `tests/` 目錄。
- 輸出 JSON schema 與原程式完全相同，僅改變寫入檔案的「數量與日期範圍」。
