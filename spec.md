# 規格書 Specification

本文檔收錄 `tw-institutional-strategy` 的約定與規格，包含 Labels、Artifact 命名、JSON Schema、Workflow 觸發條件、Issue Body 欄位等。開發新腳本或 workflow 前請先閱讀本文件。

---

## 1. Label 規格

所有 Label 由 `scripts/setup-labels.sh` 建立，分為四類：策略、狀態、風險、結果。

### 1.1 策略 Labels

| Label | 顏色 | 用途 |
|---|---|---|
| `setup-a` | `#0075ca` | Setup A 候選股 |
| `setup-b` | `#0052cc` | Setup B 候選股 |
| `setup-c` | `#003d99` | Setup C 候選股 |

### 1.2 狀態 Labels

| Label | 顏色 | 用途 |
|---|---|---|
| `screened` | `#e4e669` | 通過初篩 |
| `signal-confirmed` | `#0e8a16` | 訊號確認，等待進場 |
| `holding` | `#006b75` | 持有中 |
| `exit-triggered` | `#d93f0b` | 出場訊號已觸發 |
| `closed` | `#eeeeee` | 已結案 |

### 1.3 風險 Labels

| Label | 顏色 | 用途 |
|---|---|---|
| `auto-ok` | `#0e8a16` | Manager 評估後核可進入 Worker Queue |
| `human-review` | `#d93f0b` | 需要人工覆核 |
| `data-missing` | `#e4e669` | 資料不完整，Audit 未通過 |
| `guardrail-blocked` | `#b60205` | 被護欄規則阻擋 |

### 1.4 結果 Labels

| Label | 顏色 | 用途 |
|---|---|---|
| `result-profit` | `#0e8a16` | 獲利結案 |
| `result-loss` | `#d93f0b` | 虧損結案 |
| `result-time-exit` | `#cccccc` | 時間出場結案 |
| `result-stoploss-hit` | `#b60205` | 觸及停損結案 |

### 1.5 Label 使用約定

- 一個 Issue 只會對應一個策略 Label（`setup-a`、`setup-b` 或 `setup-c`）。
- Issue 結案時必須同時具有 `closed` 與一個 `result-*` Label。
- `result-stoploss-hit` 獨立於 `result-profit` / `result-loss`，僅表示觸及停損；報表會分開統計。
- `data-missing` 用於計算 Audit 一次通過率；曾被貼過此 Label 即視為未一次通過。

---

## 2. Issue Title 格式

```
[Setup-{A|B|C}][YYYYMMDD] {ticker} {name}
```

範例：

```
[Setup-A][20260721] 2330 台積電
```

---

## 3. Issue Body 欄位

### 3.1 Setup A 必填欄位

```markdown
- **ticker**: 股票代號
- **screen_date**: 篩選日期
- **avg_volume_20d_m**: 20 日均量（百萬）
- **foreign_5d_net**: 外資 5 日淨買超
- **trust_5d_net**: 投信 5 日淨買超
- **close_vs_ma20**: above / below
- **ma20_direction**: 上升 / 下降 / 走平
- **entry_zone**: 進場區間
- **stop_loss_price**: 停損價
- **position_size_lots**: 張數（人工填寫）
- **risk_r_pct**: 風險佔比 %（人工填寫，≤ 1.0）
- **artifact_run_id**: 產生該候選股的 workflow run ID
```

### 3.2 Setup B 必填欄位

```markdown
- **ticker**
- **screen_date**
- **avg_volume_20d_m**
- **trust_10d_net**: 投信 10 日淨買超
- **trust_10d_buy_days**: 投信 10 日買超天數（必須 ≥ 7）
- **foreign_10d_direction**: 外資 10 日方向
- **close_vs_ma20**
- **breakout_price**: 突破價
- **entry_zone**
- **stop_loss_price**
- **position_size_lots**
- **risk_r_pct**
- **artifact_run_id**
```

### 3.3 Setup C 必填欄位

```markdown
- **ticker**
- **screen_date**
- **market_cap_b**: 市值（億）
- **foreign_20d_net**: 外資 20 日淨值（必須為負）
- **foreign_recent_3d**: 外資近 3 日是否轉買（true / false，必須為 true）
- **price_bottom_status**: 底部狀態
- **entry_day**: 進場日（僅允許 2、3、4）
- **entry_zone**
- **stop_loss_price**
- **position_size_lots**
- **risk_r_pct**
- **artifact_run_id**
```

### 3.4 進場後額外欄位

進場後由人工或 monitor 在評論中補充：

```markdown
- **setup_type**: a / b / c
- **entry_date**: YYYY-MM-DD
- **entry_price**: 進場價格
```

---

## 4. Artifact 命名規格

| Workflow | Artifact 名稱 | 內容路徑 |
|---|---|---|
| `00-data-fetch.yml` | `institutional-data-{run_id}` | `data/raw/YYYYMMDD.json`、 `data/rolling/YYYYMMDD_rolling.json` |
| `10-screener-setup-a.yml` | `screener-a-{run_id}` | `data/screener/screener_result_a_YYYYMMDD.json` |
| `20-manager-loop.yml` | `manager-report-{run_id}` | `data/manager/manager_report_YYYYMMDD.json` |
| `30-signal-monitor.yml` | `monitor-report-{run_id}` | `data/monitor/monitor_report_YYYYMMDD.json` |
| `40-exit-checker.yml` | `exit-checker-report-{run_id}` | `data/exit-checker/exit_report_YYYYMMDD.json` |
| `99-guardrail-check.yml` | `guardrail-report-{run_id}` | `data/guardrail/check_result_YYYYMMDD.json` |

`YYYYMMDD` 為台灣時間的日期，`{run_id}` 為 GitHub Actions run ID。

---

## 5. JSON Schema

### 5.1 Guardrail Report

檔案：`data/guardrail/check_result_YYYYMMDD.json`

```json
{
  "timestamp": "2026-07-28T01:53:35.261736",
  "is_trading_day": true,
  "api_reachable": true,
  "data_date_correct": true,
  "current_holding_count": 3,
  "today_screener_done": false,
  "overall_pass": true
}
```

### 5.2 Manager Report

檔案：`data/manager/manager_report_YYYYMMDD.json`

```json
{
  "date": "2026-07-28",
  "market_drop_pct": -3.0,
  "market_warning_triggered": true,
  "current_holding_count": 6,
  "holding_cap_triggered": true,
  "processed_issue_count": 1,
  "screened_issue_count": 3,
  "auto_ok_granted_count": 0,
  "screened_blocked_count": 3
}
```

### 5.3 Monitor Report

檔案：`data/monitor/monitor_report_YYYYMMDD.json`

```json
{
  "date": "2026-07-28",
  "raw_date": "20260727",
  "processed_count": 1,
  "exit_triggered_count": 1,
  "holdings": [
    {
      "issue_number": 42,
      "ticker": "2330",
      "setup_type": "a",
      "entry_price": 100.0,
      "close": 90.0,
      "pnl_pct": -10.0,
      "exit_signals": ["..."],
      "partial_signals": [],
      "stoploss_triggered": true,
      "stopprofit_reminder": false
    }
  ]
}
```

### 5.4 Exit Checker Report

檔案：`data/exit-checker/exit_report_YYYYMMDD.json`

由 `scripts/exit-checker/exit_checker.py` 讀取 `monitor_report` 後產生，記錄實際執行的出場 Label 操作。

```json
{
  "date": "2026-07-28",
  "source_monitor_run_id": "1234567890",
  "processed_count": 3,
  "exit_triggered_count": 1,
  "exits": [
    {
      "issue_number": 42,
      "ticker": "2330",
      "exit_reason": "stop_loss",
      "stoploss_triggered": true,
      "labels_added": ["exit-triggered", "result-stoploss-hit"],
      "labels_removed": ["holding"]
    }
  ]
}
```

### 5.5 Weekly Report

檔案：`docs/data/report_YYYYWW.json`

```json
{
  "report_year": 2026,
  "report_week": 30,
  "report_date": "2026-07-31",
  "generated_at": "2026-07-31T18:30:00+08:00",
  "system_health": {
    "total_screened_this_week": 5,
    "audit_pass_rate": 0.8,
    "guardrail_triggered_count": 1,
    "human_review_count": 0
  },
  "strategy_performance": {
    "setup_a": {
      "closed_count": 2,
      "win_count": 1,
      "lose_count": 1,
      "stoploss_count": 0,
      "win_rate": 0.5
    },
    "setup_b": { "closed_count": 0, "win_count": 0, "lose_count": 0, "stoploss_count": 0, "win_rate": 0.0 },
    "setup_c": { "closed_count": 0, "win_count": 0, "lose_count": 0, "stoploss_count": 0, "win_rate": 0.0 }
  },
  "current_holdings": {
    "total": 2,
    "by_setup": { "a": 1, "b": 1, "c": 0 },
    "holdings": [
      {
        "issue_number": 42,
        "title": "[Setup-A][20260727] 2330 台積電",
        "setup": "a",
        "days_held": 4,
        "pnl_pct": "3.5"
      }
    ]
  }
}
```

### 5.6 Raw Institutional Data

檔案：`data/raw/YYYYMMDD.json`

由 `scripts/data/fetch_institutional.py` 寫入的單日機構籌碼原始資料。

```json
{
  "fetch_date": "2026-07-31",
  "fetch_timestamp": "2026-07-31T18:30:00",
  "source_url": "https://www.twse.com.tw/rwd/zh/fund/T86?date=20260731&selectType=ALLBUT0999",
  "record_count": 101,
  "data": [
    {
      "ticker": "2330",
      "name": "台積電",
      "foreign_buy": 1000,
      "foreign_sell": 500,
      "foreign_net": 500,
      "trust_buy": 2000,
      "trust_sell": 1000,
      "trust_net": 1000,
      "dealer_net": 300
    }
  ]
}
```

### 5.7 Rolling Metrics

檔案：`data/rolling/YYYYMMDD_rolling.json`

由 `scripts/data/compute_rolling.py` 寫入的滾動指標資料。當可用交易日少於 20 個時，`days_used` 會標註實際使用天數（降級模式）。

```json
{
  "fetch_date": "2026-07-31",
  "fetch_timestamp": "2026-07-31T18:30:00",
  "source_url": "https://www.twse.com.tw/rwd/zh/fund/T86?date=20260731&selectType=ALLBUT0999",
  "record_count": 101,
  "days_used": 20,
  "data": [
    {
      "ticker": "2330",
      "name": "台積電",
      "foreign_buy": 1000,
      "foreign_sell": 500,
      "foreign_net": 500,
      "trust_buy": 2000,
      "trust_sell": 1000,
      "trust_net": 1000,
      "dealer_net": 300,
      "foreign_5d_net": 2500,
      "trust_5d_net": 5000,
      "trust_10d_net": 10000,
      "trust_10d_buy_days": 7,
      "foreign_10d_net": 5000,
      "foreign_20d_net": 10000,
      "foreign_recent_3d_all_buy": true
    }
  ]
}
```

---

## 6. Workflow 觸發條件

| Workflow | 觸發條件 | 說明 |
|---|---|---|
| `00-data-fetch.yml` | `schedule` | 每個交易日收盤後約 16:30；首次執行補抓 25 日，之後還原前次 artifact 並只抓當日；fetch 因跳過日期 exit 1 時仍上傳 artifact（if: always()） |
| `10-screener-setup-a.yml` | `workflow_run` | `00-data-fetch.yml` 成功後執行（僅 conclusion == 'success'） |
| `20-manager-loop.yml` | `workflow_run` | `10-screener-setup-a.yml` 完成後，且 conclusion 為 success 或 failure 時執行（排除 cancelled） |
| `30-signal-monitor.yml` | `workflow_run` | `20-manager-loop.yml` 成功後 |
| `40-exit-checker.yml` | `workflow_run` | `30-signal-monitor.yml` 成功後 |
| `50-audit-check.yml` | `issues` / `issue_comment` | Issue 被標記 `screened`/`signal-confirmed`/`holding`，或留言 `/re-audit` |
| `60-performance-report.yml` | `schedule` / `workflow_dispatch` | 每週五台灣時間 18:30，或可手動觸發 |
| `99-guardrail-check.yml` | `workflow_call` | 被其他 workflow 呼叫 |

---

## 7. 計算規則

### 7.1 Audit 一次通過率

```
pass_rate = （本週新建 screened Issue 中沒有被貼過 data-missing 的數量）/（本週新建 screened Issue 總數）
```

若本週無 screened Issue，則定義為 `1.0`。

### 7.2 策略勝率

```
win_rate = win_count / closed_count
```

若 `closed_count` 為 0，則定義為 `0.0`。

### 7.3 Guardrail 攔截次數

計算本週所有 `guardrail-report-*` artifact 中，`check_result_*.json` 的 `overall_pass` 為 `false` 的數量。

### 7.4 進場天數

```
days_held = report_date - entry_date（日曆天數）
```

### 7.5 目前損益

從 Issue 的最新 monitor 評論中擷取 `相對進場損益：{value}%`；若無則顯示 `N/A`。

---

## 8. GitHub Pages 部署規格

- 來源 branch：`gh-pages`
- 來源 folder：`/(root)`
- 部署內容：`docs/` 目錄下的所有檔案
- 保留歷史檔案：`peaceiris/actions-gh-pages` 設定 `keep_files: true`
- 預期網址：`https://<owner>.github.io/tw-institutional-strategy/`
- 手動啟用步驟見 `docs/SETUP_PAGES.md`

---

## 9. 檔案與目錄命名約定

- Python scripts：`scripts/<agent>/<descriptive_name>.py`
- Tests：`tests/test_<module_name>.py`
- Workflows：`.github/workflows/<NN>-<descriptive-name>.yml`
- Data artifacts：`data/<agent>/<descriptive_name>_YYYYMMDD.json`
- Weekly report：`docs/data/report_YYYYWW.json`
- HTML dashboard：`docs/index.html`

---

## 10. 開發與測試約定

- 所有與 GitHub 互動的腳本透過 `_run_gh(args)` 呼叫 `gh` CLI。
- 測試使用 `unittest.mock.patch` 模擬 `_run_gh`、日期函式與外部 API。
- 新增 workflow 必須搭配對應的 `tests/test_*.py`。
- 執行 `pytest tests/` 應全部通過後再提交。
- 不從 Issues 以外的地方讀取「交易結果」；不自行計算策略勝率，只從 Labels 統計。
