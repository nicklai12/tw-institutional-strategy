# GitHub Pages 設定說明

本儀表板由 `.github/workflows/60-performance-report.yml` 自動部署到 `gh-pages` branch，使用的是 `peaceiris/actions-gh-pages` action。

## 一次性手動設定

1. 進入 GitHub 上的 repository 頁面。
2. 點選 **Settings** > **Pages**。
3. 在 **Build and deployment** 區塊，選擇 **Deploy from a branch**。
4. Branch 選擇 `gh-pages`，folder 選擇 `/(root)`，然後點選 **Save**。
5. 等待約 1~2 分鐘，Pages 就會完成首次部署。

## 預期 URL

部署完成後，儀表板網址為：

```
https://<owner>.github.io/tw-institutional-strategy/
```

請將 `<owner>` 替换為 repository 擁有者的 GitHub 帳號或組織名稱。

## 注意事項

- `60-performance-report.yml` 每週五台灣時間 18:30 自動執行，並將 `docs/` 推送到 `gh-pages` branch。
- `peaceiris/actions-gh-pages` 的 `keep_files: true` 設定會保留 `gh-pages` 上的歷史週報（例如 `report_202630.json`），不會被後續部署刪除。
- `main` branch 不會被此 workflow 修改；只有 `gh-pages` branch 會被更新。
- 如果首次部署後看不到頁面，請確認 repository 的 Pages 權限為公開，或組織層級允許 GitHub Pages。
