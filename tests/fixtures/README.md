# Oracle Fixtures

本目錄存放用於迴歸測試 `tests/test_filter.py` 中 `filter_setup_a` 邏輯的
input/output fixture。

## 檔案命名

- `oracle_input_YYYY-MM-DD.json`：單一交易日的原始法人＋股價資料
- `oracle_output_YYYY-MM-DD.json`：由 input 產生的預期 Setup A 候選名單

## 資料來源

- **三大法人買賣超**：TWSE `fund/T86` 端點
  - URL：`https://www.twse.com.tw/fund/T86?response=json&date=YYYYMMDD&selectType=ALL`
  - 提供每日各股票的外資與投信買賣超（net buy/sell）。
- **股價 / 均線資料**：TWSE `exchangeReport/STOCK_DAY` 端點
  - URL：`https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&stockNo=TICKER&date=YYYYMMDD`
  - 提供指定月份的日 K 開高低收、成交金額與成交量。

## 欄位計算方式

### 5 日外資 / 投信合計買賣超

對每檔股票，取 fixture 日期往前連續 5 個交易日的單日 `foreign_net` 與
`trust_net` 分別加總。

### MA20

使用 fixture 當月份與前月份的日 K 資料，取最近 20 個交易日的收盤價，
計算算術平均。

### ma20_direction

比較「今日 MA20」與「5 個交易日前的 MA20」：

- `rising`：今日 MA20 比 5 日前高，且差距 > 0.1%
- `flat`：絕對差距 ≤ 0.1%
- `falling`：其他情況

### 流動性門檻

`avg_volume_20d` 為近 20 個交易日平均每日成交金額（成交金額），單位為「千元」。
股票必須滿足：

```
avg_volume_20d >= 200_000   # 即近 20 日均成交金額 ≥ 2 億元
```

### Setup A 篩選條件

必須同時符合以下 5 項：

1. `avg_volume_20d >= 200_000`
2. `foreign_5d_net > 0`
3. `trust_5d_net > 0`
4. `close > ma20`
5. `ma20_direction == "rising"`

## 人工驗證流程

每個 output fixture 都包含：

```json
{
  "manually_verified_by": "PENDING",
  "verified_at": null
}
```

產生 fixture 後，建議人工至 TWSE 網站抽查每天至少一筆候選股票，確認無誤後
修改 output 檔案：

```json
{
  "manually_verified_by": "您的名字",
  "verified_at": "2026-07-27T09:00:00"
}
```

這兩個欄位僅供紀錄用，不會被自動化測試使用。
