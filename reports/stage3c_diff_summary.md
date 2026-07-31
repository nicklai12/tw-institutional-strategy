# Stage 3C Diff 摘要：00-data-fetch.yml

## 修改目標

修改 `.github/workflows/00-data-fetch.yml`，使其在執行 `fetch_institutional.py` 之前先嘗試還原前一次成功執行的 `institutional-data-*` artifact；若無歷史 artifact 則以 `--backfill-days 25` 進行一次性補抓，否則只抓今天（`--backfill-days 0`）。

---

## 變更表格

| 步驟 | 變更 | 原因 |
|---|---|---|
| 新增 `Step 1 - Restore historical raw data` | 透過 `gh run list` 查找最近一次成功的 `00-data-fetch.yml` run，再透過 `gh run download` 下載其 artifact 並將 `data/` 還原到工作目錄 | 讓本次執行能繼承前 20 個交易日的 raw 資料，避免每次都全量 backfill |
| `Step 1` 輸出 `first_run` | 根據是否成功還原 artifact 設定 `steps.restore.outputs.first_run` | 供下一步決定要 backfill 25 天或只抓今天 |
| 修改 `Step 2 - Fetch institutional data` | 依 `first_run` 判斷執行 `--backfill-days 25` 或 `--backfill-days 0` | 首次執行補抓歷史，後續只抓今天，維持冪等性 |
| Artifact upload | 不變 | 維持規格書 `institutional-data-{run_id}` 命名與 `data/` 內容路徑 |

---

## 還原邏輯說明

1. 使用 `gh run list --workflow=00-data-fetch.yml --branch=${{ github.ref_name }} --status=success --limit=1` 查詢最近一次成功的同名 workflow run ID。
2. 若查無結果或命令失敗，設定 `first_run=true` 並退出還原步驟。
3. 使用 `gh run download <run-id> --dir /tmp/previous-artifact` 下載該 run 的所有 artifact。
4. 在下載目錄中尋找 `institutional-data-*` 目錄，並將其下的 `data/` 複製到工作目錄的 `data/`。
5. 統計 `data/raw/*.json` 數量並輸出 log；若結構不符則退回 `first_run=true`。

---

## 注意事項

- `GH_TOKEN: ${{ github.token }}` 用於 `gh` CLI 認證。若 repository 的 workflow permissions 設為預設 restricted，可能需要在 workflow 或 job 層級加上 `permissions: actions: read`。
- `--branch=${{ github.ref_name }}` 限制只查找同分支的歷史 run，避免跨分支 artifact 混淆。
- 找不到 artifact、下載失敗、或 artifact 結構不符時，皆會退回到 `first_run=true`，確保 workflow 不中斷。
- 未修改 `fetch_institutional.py`。
- 未修改 `compute_rolling.py`。
- 未修改任何其他 workflow YAML。
- 未修改 `tests/` 目錄。

---

## 驗收指令

手動觸發 workflow：

1. 進入 GitHub 倉庫 → Actions → `00 Data Fetch` → Run workflow
2. 觀察 log，預期出現以下其中一種：

```
# 首次執行
First run, backfilling 25 days
...
OK: backfill 完成，成功寫入 25 個交易日，跳過已存在 0 個
```

```
# 非首次執行
Found previous successful run: 1234567890
Restored 20 raw files from previous artifact (run 1234567890)
Restoring from previous artifact, fetching today only
SKIP: 20260731 已存在
```

3. 繼續檢查：
   - `Step 3 - Compute rolling metrics` 的 log **不應出現** `WARNING: 原始檔案不足`
   - `Step 4 - Upload artifacts` 成功
   - 下載 artifact 後解壓，確認 `data/raw/` 下包含 `>= 20` 個 `YYYYMMDD.json` 檔案
