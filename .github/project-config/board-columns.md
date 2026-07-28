# Projects Board 欄位與自動化規則

本文件定義 tw-institutional-strategy 的 GitHub Projects Board 欄位，以及 Issue/Label 與欄位之間的自動化對應。

## 欄位一覽

| 欄位名稱（GitHub Projects） | 用途說明 | 自動化規則 |
|---|---|---|
| 待篩選（Backlog） | 新 Issue 預設進入此欄，等待篩選與資料補全 | 新 Issue 建立時自動移入 |
| 通過初篩（Screened） | 已通過初篩條件，資料欄位完整 | 貼上 `screened` Label 後自動移入 |
| 信號確認（Signal） | 符合進場信號，等待實際下單或人工確認 | 貼上 `signal-confirmed` Label 後自動移入 |
| 持有監控（Holding） | 已建立倉位，進行日常風險監控 | 貼上 `holding` Label 後自動移入 |
| 出場信號（Exit） | 觸發出場條件（停利、停損或時間出場） | 貼上 `exit-triggered` Label 後自動移入 |
| 已結算（Closed） | 倉位已結束，等待結算與檢討 | Issue 關閉後自動移入 |

## Label → 欄位對照

```
screened          → 通過初篩（Screened）
signal-confirmed  → 信號確認（Signal）
holding           → 持有監控（Holding）
exit-triggered    → 出場信號（Exit）
Issue closed      → 已結算（Closed）
```

## 注意事項

- 一個 Issue 同時只應存在於一個欄位，自動化規則以「最後貼上的狀態 Label」為準。
- 若同時貼上 `human-review` 與狀態 Label，仍會依狀態 Label 移動欄位；`human-review` 僅作為風險標記，不自動改變欄位。
- 手動移動欄位不會自動移除 Label，建議同步更新 Label 以維持一致性。
