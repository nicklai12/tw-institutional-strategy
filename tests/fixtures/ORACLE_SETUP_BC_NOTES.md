# Setup B / Setup C Oracle Fixtures 說明

本目錄下的 `oracle_*_b_*`、`oracle_*_c_*`、`oracle_*_rolling_*`、`oracle_*_signal_*` 檔案是依據 `spec/setup-bc-lock` 合併後的 `system-map.md` / `spec.md` 所設計的測試標準答案。

## Setup B Screener Oracle

檔案：
- `oracle_setup_b_input_2026-08-01.json`
- `oracle_setup_b_output_2026-08-01.json`

對應規格：
- `spec.md` 3.2 Setup B 必填欄位
- `spec.md` 7.8 Setup B 外資 10 日方向計算

案例：
| 股票 | 預期結果 | 驗證規則 |
|---|---|---|
| B001 SetupB-Pass | 入選 | 投信 10 日淨買超 750 > 0、買超天數 10 ≥ 7；外資 10 日方向 neutral（ratio ≈ 2.8% < 5%）；close 105 > MA20 89.8；突破日成交量 60M 對照 20 日均量 50.5M 未爆量。 |
| B002 SetupB-TrustDaysLow | 排除 | 投信買超天數 6 < 7。 |
| B003 SetupB-ForeignSell | 排除 | 外資 10 日方向 selling（ratio ≈ -6.6% < -5%）。 |

## Setup C Screener Oracle

檔案：
- `oracle_setup_c_input_2026-08-01.json`
- `oracle_setup_c_output_2026-08-01.json`

對應規格：
- `spec.md` 3.3 Setup C 必填欄位
- `README.md` 市值門檻護欄

案例（市值門檻採用建議值 1000 億）：
| 股票 | 預期結果 | 驗證規則 |
|---|---|---|
| C001 SetupC-Pass | 入選 | 市值 5000 億 ≥ 1000 億；外資 20 日淨值 -1450 < 0；近 3 日外資連買；foreign_buy_streak_day=3；price_bottom_status=higher_lows。 |
| C002 SetupC-Foreign20dPositive | 排除 | 外資 20 日淨值為正。 |
| C003 SetupC-Recent3dNotBuy | 排除 | 最近 3 日外資未連買。 |
| C004 SetupC-MarketCapLow | 排除 | 市值 500 億 < 1000 億。 |

## compute_rolling Oracle（foreign_buy_streak_day）

檔案：
- `oracle_rolling_bc_input_2026-08-01.json`
- `oracle_rolling_bc_output_2026-08-01.json`

對應規格：
- `spec.md` 5.7 / 5.7.1
- `spec.md` 7.6.3 Setup C 進場公式

說明：輸入為 5 個交易日的 raw data，外資淨買超序列為 `[-10, -20, +5, +15, +25]`，最後 3 日均為正，連買天數為 3，因此輸出 `foreign_buy_streak_day = 3`。

## Signal Monitor Oracle

### Setup B 進場

檔案：
- `oracle_signal_b_entry_input_2026-08-01.json`
- `oracle_signal_b_entry_output_2026-08-01.json`

對應規格：`spec.md` 7.6.2

- 量縮不破案例：T+1 收盤 102 ≥ 突破價 100，成交量 40 ≤ 50×0.8，預期進場。
- 跌破突破點案例：收盤 98.5 < 100，不進場。
- 未量縮案例：成交量 45 > 40，不進場。

### Setup C 進場

檔案：
- `oracle_signal_c_entry_input_2026-08-01.json`
- `oracle_signal_c_entry_output_2026-08-01.json`

對應規格：`spec.md` 7.6.3

- 連買第 3 天：streak=3，預期進場，entry_zone=[99,101]。
- 連買第 1 天：streak=1，不進場。

### Setup B 出場

檔案：
- `oracle_signal_b_exit_input_2026-08-01.json`
- `oracle_signal_b_exit_output_2026-08-01.json`

對應規格：`spec.md` 7.7.2

- 投信連續 2 日賣超 + 收盤跌破 MA10 與 20 日前低，預期觸發 E1（先出一半）與 E2（全出）。
- pnl ≈ +2.22%，未觸及 -6% 停損。

### Setup C 出場

檔案：
- `oracle_signal_c_exit_input_2026-08-01.json`
- `oracle_signal_c_exit_output_2026-08-01.json`

對應規格：`spec.md` 7.7.3

- 外資連續 2 日轉賣 + 收盤跌破 10 日低點，預期觸發 E1 與 E2。
- pnl ≈ -1.02%，未觸及 -5% 停損，停利區間 8–12% 未達。
