# 規格書 Specification

本文檔收錄 `tw-institutional-strategy` 的約定與規格，包含 Labels、Artifact 命名、JSON Schema、Workflow 觸發條件、Issue Body 欄位等。開發新腳本或 workflow 前請先閱讀本文件。

---

## 0. 版本異動說明

> 本次更新配合 `system-map.md` 的流程調整：Workflow 觸發鏈重排、`30-signal-monitor` 新增進場訊號判斷職責。受影響章節：**第 1.5 節**（Label 使用約定）、**第 5.3 節**（Monitor Report Schema）、**第 6 節**（Workflow 觸發條件）、**第 7 節**（新增 7.6 進場訊號判斷規則）。其餘章節未變動。
>
> ⚠️ 本次更新中，`signal-confirmed` 標記時是否移除 `screened`/`auto-ok`、以及 `entry_zone` 的資料來源，屬於**尚待確認的假設**，詳見 `system-map.md` 第 0 節。

---

> **本次更新（Setup B/C 規格鎖定）：**
> 1. Workflow 觸發鏈擴充：在 `00-data-fetch.yml` 完成後，並行觸發 `10-screener-setup-a.yml`、`11-screener-setup-b.yml`、`12-screener-setup-c.yml`；三個 screener 產生的 `screened` Issue 皆由同一個 `20-manager-loop.yml` 統一評估。
> 2. `20-manager-loop.yml` 的 `workflow_run` 觸發條件調整為同時監聽 `10/11/12` 三個 workflow 的 `completed` 事件。
> 3. `scripts/data/compute_rolling.py` 新增 `foreign_10d_direction`（Setup B 外資 10 日方向）與 `foreign_buy_streak_day`（Setup C 外資連買天數）兩個欄位。
> 4. `scripts/monitor/signal_monitor.py` 進場判斷擴充 Setup B（突破後量縮不破）與 Setup C（外資連買第 N 天）規則；出場判斷已依 `setup_type` 分流，Setup A/B/C 規則均已存在於程式碼中。
> 5. Issue body 欄位新增 Setup B 的 `breakout_date`、`breakout_volume_m`，以及 Setup C 的 `foreign_buy_streak_day`（參考欄位，由 screener 計算後寫入）。
>
> ⚠️ **本次 Setup B/C 規格鎖定仍有以下項目待人工確認：**
> - `foreign_10d_direction` 判定「明顯大賣」的具體閾值（目前僅定義 buying / neutral / selling 三態，閾值未決）。
> - Setup B 量縮條件的成交金額比率閾值，以及「隔天/第三天」的確切天數定義（T+1 / T+2 或 T+2 / T+3）。
> - Setup C 進場是以 Issue body 的 `entry_day` 單一固定日為準，還是第 2~4 天任一天均可進場。
> - 停損觸發應以 Issue body 的 `stop_loss_price` 為準，還是沿用 `signal_monitor.py` 目前的 `setup_type` 百分比對照表（a: -7%、b: -6%、c: -5%）。
> - Setup C 的 `entry_zone` 在 screener 階段應如何預填（進場日當天才由 monitor 動態決定當日價格區間）。

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
| `signal-confirmed` | `#0e8a16` | 訊號確認，等待進場（由 `30-signal-monitor.yml` 判斷價格回落至 `entry_zone` 後自動標記） |
| `holding` | `#006b75` | 持有中 |
| `exit-triggered` | `#d93f0b` | 出場訊號已觸發 |
| `closed` | `#eeeeee` | 已結案 |

### 1.3 風險 Labels

| Label | 顏色 | 用途 |
|---|---|---|
| `auto-ok` | `#0e8a16` | Manager 評估後核可進入 Worker Queue，等待 Signal Monitor 判斷進場訊號 |
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
- **【新增，⚠️ 待確認】** Issue 標記 `signal-confirmed` 時，同步移除 `screened` 與 `auto-ok`，避免同一 Issue 疊加多個狀態標籤，也避免 Manager Loop 重複評估已進入下一階段的 Issue。

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
- **entry_zone**: 進場區間（⚠️ 本次調整後，此欄位亦作為 signal_monitor 進場訊號判斷的資料來源，見 7.6 節）
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
- **foreign_10d_direction**: 外資 10 日方向（buying / neutral / selling，由 `foreign_10d_net` 與閾值決定）
- **close_vs_ma20**
- **breakout_price**: 突破點位（近 20 日區間高點）
- **breakout_date**: 突破日期（YYYY-MM-DD，用於計算「隔天/第三天」等待天數）
- **breakout_volume_m**: 突破日成交金額（百萬台幣，用於 signal monitor 量縮判斷）
- **entry_zone**: 建議進場區間（靜態參考值，實際進場公式見 7.6.2）
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
- **foreign_recent_3d**: 外資近 3 日是否轉買（true / false，必須為 true；對應 rolling 欄位 `foreign_recent_3d_all_buy`）
- **foreign_buy_streak_day**: 截至 screen_date 外資連續買超天數（參考欄位，由 screener 計算後寫入）
- **price_bottom_status**: 底部狀態
- **entry_day**: 進場日（僅允許 2、3、4）
- **entry_zone**: 建議進場區間（靜態參考值，實際進場日由 monitor 以當日價格區間動態確認，見 7.6.3）
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

**【新增欄位】** `entry_checked_count`、`entry_confirmed_count`、`entry_candidates` 用於記錄進場訊號判斷結果；`holdings` 為既有的出場訊號判斷結果，結構不變。

```json
{
  "date": "2026-07-28",
  "raw_date": "20260727",
  "entry_checked_count": 2,
  "entry_confirmed_count": 1,
  "entry_candidates": [
    {
      "issue_number": 55,
      "ticker": "2454",
      "entry_zone": "95.20-98.50",
      "close": 96.80,
      "entry_confirmed": true
    }
  ],
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
      "foreign_10d_direction": "buying",
      "foreign_20d_net": 10000,
      "foreign_recent_3d_all_buy": true,
      "foreign_buy_streak_day": 3
    }
  ]
}
```

#### 5.7.1 Setup B/C 新增欄位說明

| 欄位 | 計算公式 | 用途 |
|---|---|---|
| `foreign_10d_direction` | 依 `foreign_10d_net` 與策略閾值判定：<br>• `foreign_10d_net` >  +threshold → `buying`<br>• `foreign_10d_net` <  -threshold → `selling`<br>• 否則 → `neutral` | Setup B 篩選條件「外資近 10 日不要明顯大賣」 |
| `foreign_buy_streak_day` | 從最新交易日往前數，連續 `foreign_net > 0` 的天數；遇到 `foreign_net ≤ 0` 即中斷 | Setup C screener 決定 `entry_day`，以及 monitor 判斷進場日 |

`threshold` 為尚未確認的策略參數，列入本文件「⚠️ 待確認」。

---

## 6. Workflow 觸發條件

| Workflow | 觸發條件 | 說明 |
|---|---|---|
| `00-data-fetch.yml` | `schedule` | 每個交易日收盤後約 18:30 TW；首次執行補抓 25 日，之後還原前次 artifact 並只抓當日；fetch 因跳過日期 exit 1 時仍上傳 artifact（if: always()） |
| `10-screener-setup-a.yml` | `workflow_run` | `00-data-fetch.yml` 完成後執行（僅 conclusion == 'success'） |
| `11-screener-setup-b.yml` | `workflow_run` | `00-data-fetch.yml` 完成後執行（僅 conclusion == 'success'） |
| `12-screener-setup-c.yml` | `workflow_run` | `00-data-fetch.yml` 完成後執行（僅 conclusion == 'success'） |
| `20-manager-loop.yml` | `workflow_run` | `10-screener-setup-a.yml`、`11-screener-setup-b.yml`、`12-screener-setup-c.yml` 完成後，且 conclusion 為 success 或 failure 時執行（排除 cancelled） |
| `30-signal-monitor.yml` | `workflow_run` | `20-manager-loop.yml` 成功後（進場訊號判斷 + 出場訊號判斷） |
| `40-exit-checker.yml` | `workflow_run` | `30-signal-monitor.yml` 成功後（不變） |
| `50-audit-check.yml` | `issues` / `issue_comment` | Issue 被標記 `screened`/`signal-confirmed`/`holding`，或留言 `/re-audit`。**注意**：`signal-confirmed` 事件在本次調整後才會被實際觸發 |
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

### 7.6 進場訊號判斷規則

Signal Monitor 對 `auto-ok` Issue 每日判斷是否進場。各 Setup 規則如下：

#### 7.6.1 Setup A

```
entry_confirmed = min(MA5, MA20) ≤ close ≤ max(MA5, MA20)
```

- `entry_zone` 數值來源：Issue body 中 screener 建立當下寫入的**靜態值**，非重新計算當下的 MA5/MA20。
- 判斷成立時，標記 `signal-confirmed`，並依 1.5 節約定同步移除 `screened`、`auto-ok`。

#### 7.6.2 Setup B

```
trading_days_after_breakout = 今日與 breakout_date 之間的交易日天數（不含 breakout_date）
entry_confirmed =
    1 ≤ trading_days_after_breakout ≤ 2
    AND close ≥ breakout_price
    AND volume_today_m ≤ breakout_volume_m × VOLUME_CONTRACTION_RATIO
```

- `breakout_date`、`breakout_price`、`breakout_volume_m` 皆來自 Issue body 的靜態值。
- `volume_today_m` 由 Signal Monitor 於判斷當日透過股價 API 取得（單位：百萬台幣）。
- `VOLUME_CONTRACTION_RATIO` 為待確認策略參數（例如 `0.9`）。
- 「隔天/第三天」的確切天數定義（T+1 / T+2 或 T+2 / T+3）亦為待確認項目；本公式暫以 T+1 / T+2 為例。
- 若條件成立，標記 `signal-confirmed`，並依 1.5 節約定同步移除 `screened`、`auto-ok`。

#### 7.6.3 Setup C

```
foreign_buy_streak_day = 截至今日外資連續買超天數（raw data 中 foreign_net > 0 的連續天數）
entry_confirmed = foreign_buy_streak_day == entry_day AND close > 0
entry_zone = [today_low, today_high]
```

- `entry_day` 來自 Issue body（`2` / `3` / `4`）。
- `today_low`、`today_high` 由 Signal Monitor 於判斷當日取得。
- 若採用「第 2~4 天任一天均可進場」的放寬版本，則條件改為 `2 ≤ foreign_buy_streak_day ≤ 4`；此選擇為待確認項目。
- 若條件成立，標記 `signal-confirmed`，並依 1.5 節約定同步移除 `screened`、`auto-ok`。

### 7.7 出場訊號判斷規則

Signal Monitor 對 `holding` Issue 每日判斷出場條件。`stoploss_triggered` 為各 Setup 通用邏輯：

```
pnl_pct = (close - entry_price) / entry_price × 100
stoploss_triggered = pnl_pct ≤ -_SETUP_STOP_LOSS_PCT[setup_type]
```

其中 `_SETUP_STOP_LOSS_PCT` 對照表為 `a: 7.0`、`b: 6.0`、`c: 5.0`。

#### 7.7.1 Setup A

| 出場條件 | 資料來源與判斷式 |
|---|---|
| E1 法人轉弱 | `raw data` 最近 3 日：`foreign_net` 連續 3 日負 或 `trust_net` 連續 3 日負 |
| E2 價格轉弱 | 股價 API：`today_close < MA20` 且 `prev_close < MA20`（連續兩日收盤跌破 MA20） |
| E3 時間停利 | `raw data` 交易日計數：`trading_days_since_entry ≥ 20` |

#### 7.7.2 Setup B

| 出場條件 | 資料來源與判斷式 |
|---|---|
| E1 投信連續賣超（先出一半） | `raw data` 最近 2 日：`trust_net` 連續 2 日負 |
| E2 跌破 MA10 / 前低（全出） | 股價 API：`close < MA10` 或 `close < recent_low_20d`；且須同時滿足 E1 |

- `partial_signals` 記錄 E1；`exit_signals` 記錄 E2。
- 當 E2 成立時，已包含 E1 條件，因此全出訊號觸發時 partial 訊號亦會存在。

#### 7.7.3 Setup C

| 出場條件 | 資料來源與判斷式 |
|---|---|
| E1 外資連續轉賣 | `raw data` 最近 2 日：`foreign_net` 連續 2 日負 |
| E2 跌破整理區間下緣 | 股價 API：`close < recent_low_10d`（以 10 日低點作為整理區間下緣） |
| 停利提醒 | `pnl_pct` 落在 `8% ~ 12%` 區間時標記 `stopprofit_reminder` |

- 規格書原始描述為「外資再度連續 2～3 日轉賣」；目前程式碼實作以連續 2 日為觸發條件。是否改為 2 日或 3 日為待確認項目。

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
