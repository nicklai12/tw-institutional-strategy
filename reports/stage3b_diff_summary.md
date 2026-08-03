# Stage 3B Diff 摘要：compute_rolling.py

## 修改目標

修改 `scripts/data/compute_rolling.py`，使其能掃描 `data/raw/` 下所有歷史 raw 檔案，取最新 20 個交易日計算 rolling 指標；當可用天數不足 20 天時，改為降級計算（不中斷），並在輸出 JSON 中標注實際使用天數。

---

## 變更表格

| 區域 | 變更 | 原因 |
|---|---|---|
| 匯入 | `+import datetime` | 輸出檔名需使用今日日期 |
| `compute_rolling()` 檔案數檢查 | `raise RuntimeError(...)` 改為 `print(WARNING ...)` | 不足 20 天時降級計算，不中斷 |
| `compute_rolling()` recent 取得 | 維持 `loaded[-20:]`，註解改為「或可用天數」 | 當檔案少於 20 個時自動取全部可用資料 |
| `compute_rolling()` 輸出 | `+days_used: len(recent)` | 讓下游與驗收知道實際使用天數 |
| `main()` 輸出檔名 | `result["fetch_date"]` 改為 `datetime.date.today().strftime("%Y%m%d")` | 規格要求輸出檔名使用今日日期 |
| `main()` 完成訊息 | 加入 `使用 {days_used} 個交易日` | 方便日誌觀察是否降級 |

---

## 降級行為說明

- `compute_rolling()` 不再因 raw 檔案不足而拋出 `RuntimeError`。
- 當 `len(loaded) < 20` 時，印出 `WARNING` 後繼續執行。
- `recent = loaded[-20:]` 在檔案少於 20 個時會自動取全部可用檔案。
- 所有 rolling 指標的窗口計算（`window_records`）會根據實際可用天數運作，例如只有 5 天資料時，`foreign_20d_net` 實際上為這 5 天的總和。
- 輸出 JSON 新增 `days_used` 欄位，下游可據此判斷是否處於降級模式。

---

## 驗收指令

```bash
# 假設 data/raw/ 已有 20 個檔案（由 Fetch Agent 準備）
python scripts/data/compute_rolling.py
# 預期：
# 1. 不出現 "WARNING: 原始檔案不足"
# 2. data/rolling/YYYYMMDD_rolling.json 存在
# 3. 該 JSON 的 days_used 欄位 = 20
cat data/rolling/*_rolling.json | python -m json.tool
```

---

## 注意事項

- 未修改 `fetch_institutional.py`。
- 未修改任何 `.github/workflows/` YAML 檔案。
- 未修改 `tests/` 目錄。
- 輸出 JSON schema 僅新增 `days_used` 欄位，其餘欄位保持不變。
