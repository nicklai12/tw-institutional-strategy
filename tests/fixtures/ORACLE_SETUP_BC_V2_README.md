# Setup B / C Oracle Fixtures v2 說明

本目錄下 `oracle_*_2026-08-0[2-4].json` 與 `oracle_*_2026-08-02.json` 為 Setup B / C 規格鎖定後的第二批測試標準答案（Oracle fixtures），對應 `spec/setup-bc-lock` 合併後的 `spec.md` / `system-map.md`。

所有數字皆經手動驗算，並於各 output 檔案的 `reason` 欄位註明計算過程與引用條文。

---

## 1. Setup B Screener Fixtures

檔案：`oracle_input_b_2026-08-0{2,3,4}.json` / `oracle_output_b_2026-08-0{2,3,4}.json`

Setup B 篩選規則參見 `spec.md` 3.2、7.8：
- 投信 10 日淨買超為正且買超天數 ≥ 7。
- 外資 10 日方向由 screener 計算：
  - `avg_daily_volume_lots = avg_volume_20d_m × 1000 / close`
  - `foreign_avg_daily_net = foreign_10d_net / 10`
  - `ratio = foreign_avg_daily_net / avg_daily_volume_lots`
  - `ratio > +5% → buying`，`ratio < -5% → selling`，其餘 `neutral`。
- 股價站上 MA20（`close_vs_ma20 = above`）。

| 檔案 | 案例 | 預期結果 | 驗證規則 |
|---|---|---|---|
| `oracle_input_b_2026-08-02.json` | B101：投信買超天數 8 ≥ 7，外資 ratio = (600/10)/(100×1000/100) = 6% → buying | 入選 | spec.md 3.2、7.8 |
| `oracle_input_b_2026-08-03.json` | B102：投信買超天數 6 < 7 | 排除 | spec.md 3.2 |
| `oracle_input_b_2026-08-04.json` | B103：外資 ratio = (-600/10)/(100×1000/100) = -6% → selling | 排除 | spec.md 3.2、7.8 |

---

## 2. Setup C Screener Fixtures

檔案：`oracle_input_c_2026-08-02.json` / `oracle_output_c_2026-08-02.json`

Setup C 篩選規則參見 `spec.md` 3.3：
- 市值 `market_cap_b ≥ 1000` 億。
- 外資 20 日合計為負（`foreign_20d_net < 0`）。
- 外資近 3 日轉為連買（`foreign_recent_3d = true`，對應 rolling 欄位 `foreign_recent_3d_all_buy`）。
- 底部型態為墊高（`price_bottom_status = higher_lows`）。
- `foreign_buy_streak_day` 為截至 screen_date 外資連續買超天數。

| 案例 | 條件 | 預期結果 | 驗證規則 |
|---|---|---|---|
| C101 | 市值 2000、20 日淨值 -1350、近 3 日連買、streak=3 | 入選 | spec.md 3.3 |
| C102 | 外資 20 日淨值 +500 | 排除 | spec.md 3.3 |
| C103 | 外資最近 3 日為 80, -10, 120，未連續買超 | 排除 | spec.md 3.3 |
| C104 | 市值 500 < 1000 | 排除 | spec.md 3.3 |

數值驗證：
- C101 / C104 的 `foreign_daily_20d` 加總 = -1700 + 350 = -1350，與 `foreign_20d_net` 一致。
- C103 的 `foreign_daily_20d` 加總 = -1700 + 190 = -1510，與 `foreign_20d_net` 一致。
- C102 的 `foreign_daily_20d` 加總 = 25 × 20 = 500，與 `foreign_20d_net` 一致。

---

## 3. Rolling Compute Fixtures

檔案：`oracle_rolling_bc_input_2026-08-02.json` / `oracle_rolling_bc_output_2026-08-02.json`

Stage 0a 規格要求 `compute_rolling.py` 新增 `foreign_buy_streak_day` 欄位（`spec.md` 5.7.1、`system-map.md` 第 0 節）。本 fixture 提供模擬 raw data（以 `daily_history` 聚合呈現）與預期 rolling 輸出。

`foreign_buy_streak_day` 定義：從最新交易日往前數，連續 `foreign_net > 0` 的天數；遇到 `foreign_net ≤ 0` 即中斷。

| 案例 | 最近 20 日外資 net 摘要 | 預期 `foreign_buy_streak_day` | 其他驗算 |
|---|---|---|---|
| R002 | 全部 +10 | 20 | foreign_20d_net=200、foreign_10d_net=100、foreign_5d_net=50、foreign_recent_3d_all_buy=true |
| R003 | 前 18 日 +10，第 19 日 -5，第 20 日 +10 | 1 | foreign_20d_net=185、foreign_10d_net=85、foreign_5d_net=45、foreign_recent_3d_all_buy=false |
| R004 | 前 19 日 +10，第 20 日 -5 | 0 | foreign_20d_net=185、foreign_10d_net=85、foreign_5d_net=35、foreign_recent_3d_all_buy=false |

---

## 4. Signal Monitor Entry Fixtures

### 4.1 Setup B Entry

檔案：`oracle_signal_b_entry_input_2026-08-02.json` / `oracle_signal_b_entry_output_2026-08-02.json`

規則（`spec.md` 7.6.2）：
```
entry_confirmed =
    trading_days_after_breakout ∈ {1, 2}
    AND close ≥ breakout_price
    AND volume_today_m ≤ breakout_volume_m × 0.8
```

共用參數：`breakout_date=2026-07-31`、`breakout_price=100`、`breakout_volume_m=50`，量縮閾值 = 40。

| 案例 | 條件 | 預期 | 驗證 |
|---|---|---|---|
| T+1 量縮不破 | today=2026-08-01, close=102, volume=40 | entry_confirmed=true | 1∈{1,2}, 102≥100, 40≤40 |
| T+2 量縮不破 | today=2026-08-02, close=101, volume=38 | entry_confirmed=true | 2∈{1,2}, 101≥100, 38≤40 |
| T+3 超過窗口 | today=2026-08-03, close=101, volume=38 | entry_confirmed=false | 3∉{1,2} |
| T+1 跌破突破價 | today=2026-08-01, close=99, volume=35 | entry_confirmed=false | 99<100 |
| T+1 未量縮 | today=2026-08-01, close=102, volume=45 | entry_confirmed=false | 45>40 |

### 4.2 Setup C Entry

檔案：`oracle_signal_c_entry_input_2026-08-02.json` / `oracle_signal_c_entry_output_2026-08-02.json`

規則（`spec.md` 7.6.3）：
```
entry_confirmed = 2 ≤ foreign_buy_streak_day ≤ 4 AND close > 0
entry_zone = [today_low, today_high]
```

| 案例 | streak | 預期 | entry_zone |
|---|---|---|---|
| 外資連買第 2 天 | 2 | true | [99, 101] |
| 外資連買第 4 天 | 4 | true | [98, 102] |
| 外資連買第 5 天 | 5 | false | null |
| 外資連買第 1 天 | 1 | false | null |

---

## 5. Signal Monitor Exit Fixtures

### 5.1 Setup B Exit

檔案：`oracle_signal_b_exit_input_2026-08-02.json` / `oracle_signal_b_exit_output_2026-08-02.json`

規則（`spec.md` 7.7、7.7.2）：
- E1：最近 2 日 `trust_net` 連續負 → `partial_signals`。
- E2：`close < MA10` 或 `close < recent_low_20d`，且須同時滿足 E1 → `exit_signals`。
- 停損：`pnl_pct ≤ -6%` → `stoploss_triggered`。

| 案例 | 條件 | pnl | partial | exit | stoploss |
|---|---|---|---|---|---|
| 僅觸發投信連續賣超 | entry=100, close=95.5, ma10=95, low20=94, trust=[-10,-20] | -4.5% | E1 | 無 | false |
| 跌破 MA10 全出 | entry=100, close=94.5, ma10=95, low20=93, trust=[-10,-20] | -5.5% | E1 | E2 | false |
| 觸及停損 | entry=100, close=93, ma10=92, low20=91, trust=[10,20] | -7.0% | 無 | 無 | true |

### 5.2 Setup C Exit

檔案：`oracle_signal_c_exit_input_2026-08-02.json` / `oracle_signal_c_exit_output_2026-08-02.json`

規則（`spec.md` 7.7、7.7.3）：
- E1：最近 2 日 `foreign_net` 連續負 → `exit_signals`。
- E2：`close < recent_low_10d` → `exit_signals`。
- 停利提醒：`pnl_pct ∈ [8%, 12%]` → `stopprofit_reminder`。
- 停損：`pnl_pct ≤ -5%` → `stoploss_triggered`。

| 案例 | 條件 | pnl | exit | stoploss | stopprofit |
|---|---|---|---|---|---|
| 外資連續轉賣且跌破整理區間 | entry=100, close=96, low10=97, foreign=[-10,-20] | -4.0% | E1+E2 | false | false |
| 觸發停利提醒 | entry=90, close=99, low10=85, foreign=[10,20] | +10.0% | 無 | false | true |
| 觸及停損 | entry=100, close=94, low10=93, foreign=[10,20] | -6.0% | 無 | true | false |

---

## 6. 與 v1 Fixture 的關係

- v1 fixture（`oracle_setup_*_input_2026-08-01.json`）保留不變。
- v2 fixture 採用 `oracle_input_b_*.json` / `oracle_input_c_*.json` 命名，擴充更多邊界案例，並與 v1 互補。
