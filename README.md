# tw-institutional-strategy

台股機構籌碼策略自動化倉庫。本倉庫以 GitHub Issues 作為候選股追蹤單、GitHub Actions 作為排程與審核引擎、GitHub Projects 作為看板，並以 `tests/fixtures/` 中的標準化測試資料作為各階段的參照基準。

---

## 系統架構圖

```mermaid
graph TD
    A[市場數據] -->|Data Agent| B[scripts/data]
    B --> C[tests/fixtures]
    B --> D[scripts/screener]
    C --> D
    D -->|10/11/12-screener-setup-{a|b|c}| E[GitHub Issues<br/>setup-a/b/c + screened]
    E -->|20-manager-loop| F2[scripts/manager]
    F2 -->|正常| G0[auto-ok]
    F2 -->|風險| G1[human-review<br/>guardrail-blocked]
    G0 -->|30-signal-monitor<br/>進場訊號判斷| G[signal-confirmed]
    E --> F[scripts/audit]
    G --> F
    F -->|未通過| FX[data-missing]
    G -. 人工判斷進場 .-> H[holding]
    H -->|30-signal-monitor<br/>出場訊號判斷| I0[monitor report]
    I0 -->|40-exit-checker| I[exit-triggered]
    I -. 人工結算 .-> J[closed]
    J --> K[scripts/report/generate_report.py]
    K --> L[GitHub Pages 每週儀表板]

    style A fill:#e1f5fe
    style E fill:#fff9c4
    style G fill:#c8e6c9
    style F fill:#ffccbc
    style J fill:#e8f5e9
    style L fill:#e1f5fe
```

> **本次流程異動**：Workflow 觸發順序調整為 `00-data-fetch → 10/11/12-screener-setup-{a|b|c} → 20-manager-loop → 30-signal-monitor → 40-exit-checker`，使當日新建的候選股能在當日完成風險評估。`30-signal-monitor` 負責「進場訊號判斷」：對已通過風險評估（`auto-ok`）的候選股，依 Setup A/B/C 各自規則（Setup A：MA5/MA20 區間；Setup B：突破後 T+1/T+2 量縮不破；Setup C：外資連買 2–4 天）判定，符合則自動標記 `signal-confirmed`，交由人工決定是否實際進場。詳細規則與待確認項目，請參考 `spec.md` 第 0 節與 7.6 節。

---

## 六個 Phase 說明

| Phase | 名稱 | 說明 |
|---|---|---|
| Phase 0 | 資料標準化 | 已產出 `tests/fixtures/oracle_input_*.json` 與 `oracle_output_*.json`，作為後續開發與測試的黃金標準。 |
| Phase 1 | 倉庫基礎建設 | 建立資料夾結構、Issue Templates、Labels、Projects Board 設定與本說明文件。 |
| Phase 2 | 數據管線 | `scripts/data/` 從 TWSE 取得機構籌碼資料，支援 `--backfill-days` 補抓最近 N 個交易日；`compute_rolling.py` 計算最近 20 日滾動指標，檔案不足時自動降級並在輸出標註 `days_used`。 |
| Phase 3 | 篩選器 | `scripts/screener/` 讀取標準化資料，依 Setup A/B/C 條件產生候選股 Issue。緊接在數據管線完成後執行，確保候選股能在當日進入後續風險評估。 |
| Phase 4 | 審核、護欄與訊號判斷 | `scripts/audit/` 在 Issue 建立或標記時執行必填欄位檢查；`scripts/manager/` 執行大盤與持倉上限護欄；`scripts/monitor/` 依 Setup A/B/C 規則判斷進場訊號（`auto-ok` → `signal-confirmed`）與出場訊號（`holding` → `exit-triggered`）。 |
| Phase 5 | 報告與追蹤 | `scripts/report/` 產生每日持倉監控、出場提醒，以及每週五自動推送到 GitHub Pages 的績效儀表板。 |

---

## 資料夾結構

```
scripts/
├── data/          # Data Agent 腳本：取得並標準化市場數據
├── screener/      # Screener 腳本：執行 Setup A/B/C 篩選
├── manager/       # Manager 腳本：大盤與持倉上限護欄評估
├── monitor/       # Monitor 腳本：進場訊號判斷、出場訊號判斷
├── exit-checker/  # Exit Checker 腳本：執行出場 Label 操作
├── audit/         # Audit 腳本：護欄檢查與風險標記
└── report/        # Report 腳本：持倉監控與績效報告

.github/
├── workflows/         # GitHub Actions Workflow
├── ISSUE_TEMPLATE/    # 三個 Setup 候選股 Issue 表單
└── project-config/    # Projects Board 欄位與自動化規則

tests/
└── fixtures/      # Phase 0 產出的標準化測試資料（請勿更動）
```

---

## Workflow 觸發時機

| Workflow | 觸發時機 | 用途 |
|---|---|---|
| `00-data-fetch.yml` | 每個交易日收盤後（約 18:30 台灣時間）透過 `schedule` 觸發 | 透過 named-artifact 還原前次成功的 `institutional-data` artifact 到 `data/`；首次執行補抓 25 個交易日，之後只抓當日；執行 `scripts/data/` 產生 `data/raw/` 與 `data/rolling/`；若當日資料無法取得或最新 raw 資料已超過 7 天，fetch 會 exit 1，但仍透過 `if: always()` 上傳 artifact |
| `10-screener-setup-a.yml` | `00-data-fetch.yml` 完成後 `workflow_run` 觸發，僅當 upstream conclusion 為 `success` 時執行 | 執行 `scripts/screener/setup_a.py` 產生 Setup A 候選股 Issue（labels: `setup-a`, `screened`） |
| `11-screener-setup-b.yml` | `00-data-fetch.yml` 完成後 `workflow_run` 觸發，僅當 upstream conclusion 為 `success` 時執行 | 執行 `scripts/screener/setup_b.py` 產生 Setup B 候選股 Issue（labels: `setup-b`, `screened`） |
| `12-screener-setup-c.yml` | `00-data-fetch.yml` 完成後 `workflow_run` 觸發，僅當 upstream conclusion 為 `success` 時執行 | 執行 `scripts/screener/setup_c.py` 產生 Setup C 候選股 Issue（labels: `setup-c`, `screened`） |
| `20-manager-loop.yml` | `10-screener-setup-a.yml`、`11-screener-setup-b.yml`、`12-screener-setup-c.yml` 完成後 `workflow_run` 觸發，當 upstream conclusion 為 `success` 或 `failure` 時執行（排除 `cancelled`） | 執行 `scripts/manager/` 檢查大盤與持倉上限護欄，對當日新建的 `screened` Issue 標記 `auto-ok` / `human-review` / `guardrail-blocked` |
| `30-signal-monitor.yml` | `20-manager-loop.yml` 成功後 `workflow_run` 觸發 | 掃描 `auto-ok` Issue，依 Setup A/B/C 規則判定進場訊號，符合則標記 `signal-confirmed` 並移除 `screened`、`auto-ok`；掃描 `holding` Issue 檢查出場條件，產生 monitor report |
| `40-exit-checker.yml` | `30-signal-monitor.yml` 成功後 `workflow_run` 觸發；或 `workflow_dispatch` 手動觸發 | 讀取 monitor report，對觸發出場/停損條件的 `holding` Issue 標記 `exit-triggered`（並視情況加上 `result-stoploss-hit`），移除 `holding`。手動觸發時需輸入 upstream `30-signal-monitor` 的 run ID |
| `50-audit-check.yml` | Issue 建立、新增 `screened`/`signal-confirmed`/`holding` Label，或留言 `/re-audit` 時觸發 | 執行 `scripts/audit/` 檢查欄位與護欄 |
| `60-performance-report.yml` | 每週五台灣時間 18:30 透過 `schedule` 觸發，或 `workflow_dispatch` 手動觸發 | 執行 `scripts/report/generate_report.py` 並部署到 GitHub Pages |
| `99-guardrail-check.yml` | 被其他 workflow 以 `workflow_call` 呼叫 | 執行 `scripts/guardrail/pre_run_check.py` 檢查資料與環境 |

### 如何查詢 Workflow Run ID

手動觸發 `40-exit-checker.yml` 時，需要輸入 upstream `30-signal-monitor.yml` 的 run ID。

**方法 1：從 GitHub Actions 頁面 URL 取得**

進入該 workflow run 的頁面，URL 最後一組數字即為 run ID：

```text
https://github.com/nicklai12/tw-institutional-strategy/actions/runs/31809342266
                                                            ^^^^^^^^^^^^^^^^
                                                            run ID
```

**方法 2：使用 GitHub CLI**

```bash
gh run list --workflow=30-signal-monitor.yml --limit=1 --json databaseId
```


Audit Action 會對每個候選股 Issue 執行以下護欄檢查。未通過者將被標記為 `data-missing`（欄位/數值不符）或由 Manager Loop 標記為 `guardrail-blocked`（風控上限觸發）。

1. **必填欄位護欄**：Issue 必須包含該 Setup 模板中的所有必填欄位；缺少任一欄位即拒絕。
2. **風險占比護欄**：`risk_r_pct` 必須 ≤ `1.0`。
3. **Setup B 投信天數護欄**：`trust_10d_buy_days` 必須 ≥ `7`。
4. **Setup C 外資淨值護欄**：`foreign_20d_net` 必須為負值。
5. **Setup C 最近三日護欄**：`foreign_recent_3d` 必須為 `true`。
6. **Setup C 進場日護欄**：`entry_day` 僅允許 `2`、`3`、`4`。
7. **市值門檻護欄**：`market_cap_b` 必須大於 Setup C screener 設定的最低門檻。預設門檻為 `1000` 億台幣，可透過 env var `MARKET_CAP_THRESHOLD_B`（或 workflow 使用的 `MARKET_CAP_THRESHOLD_BILLIONS`）調整。
8. **持倉上限護欄**：目前 `holding` 中的 Issue 數量達 6 檔時，Manager Loop 會標記新候選為 `guardrail-blocked`，暫停開新倉。
9. **大盤急跌護欄**：加權指數單日跌幅超過 2% 時，Manager Loop 會將當日新候選標記為 `human-review`，暫停自動核可。

---

## 如何手動介入

當自動化流程遇到需要人工判斷的情境時，可透過 Label 進行手動介入：

- **`human-review`**：貼上此 Label 後（或由 Manager Loop 自動貼上），對應 Issue 建議暫停自動狀態轉換，等待人工覆核。**注意**：目前系統不會自動移除此標籤，需人工判斷風險解除後手動移除。
- **`auto-ok`**：表示該 Issue 已通過 Manager Loop 的大盤/持倉護欄檢查，會進入 `30-signal-monitor.yml` 的進場訊號判斷階段，依 Setup A/B/C 各自規則等待進場訊號成立。
- **`signal-confirmed`**：表示進場訊號已成立（Setup A：收盤價回落至 MA5/MA20 區間；Setup B：突破後 T+1/T+2 量縮不破；Setup C：外資連買 2–4 天），**仍需人工判斷是否實際進場**。若決定進場，請手動將 Label 改為 `holding`，並在 Issue 留言補上 `entry_date`、`entry_price`、`setup_type` 三個欄位，供後續出場監控使用。
- **`data-missing`**：表示資料不完整或欄位不符規則，Audit Action 會留下評論要求補齊欄位；補齊後留言 `/re-audit` 重新觸發驗證。
- **`guardrail-blocked`**：表示未通過風控護欄（大盤急跌或持倉滿），建議人工評估後續是否有必要手動介入。

**注意**：手動貼上狀態 Label（`screened`、`signal-confirmed`、`holding`、`exit-triggered`）仍會觸發 Projects Board 欄位移動，即使同時貼有 `human-review`。建議先完成人工覆核，再貼上狀態 Label。

---

## 每週績效儀表板

`scripts/report/generate_report.py` 每週五台灣時間 18:30 自動執行，彙整以下資訊並推送到 GitHub Pages：

- **系統健康指標**：本週新增候選 Issue 數、Audit 一次通過率、Guardrail 攔截次數、人工介入次數。
- **策略績效指標**：Setup A/B/C 的總筆數、獲利筆數、虧損筆數、停損筆數與勝率（僅從 Issue Labels 讀取，不做額外計算）。
- **目前持倉狀態**：holding 中的 Issue 數量、各 Setup 分布、每檔進場天數與最新損益。

儀表板網址：`https://<owner>.github.io/tw-institutional-strategy/`

首次使用前，請參考 `docs/SETUP_PAGES.md` 在 Repository Settings > Pages 中選擇 `gh-pages` branch 作為來源。

---

## 快速開始

1. 確保 `tests/fixtures/` 已存在 Phase 0 資料。
2. 執行 `scripts/setup-labels.sh` 建立所有 Labels。
3. 在 GitHub Projects 中建立 Board，並參考 `.github/project-config/board-columns.md` 設定六個欄位與自動化規則。
4. 參考 `docs/SETUP_PAGES.md` 開啟 GitHub Pages，讓 `60-performance-report.yml` 每週自動部署儀表板。
5. 執行 `pytest tests/` 驗證所有腳本與 workflow 的邏輯。

---

## 授權與貢獻

本倉庫為策略自動化基礎設施，所有業務邏輯與交易策略程式碼請依各自 Phase 獨立開發，避免在基礎建設階段混入策略計算。
