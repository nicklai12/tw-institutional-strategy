#!/usr/bin/env bash
# 批次建立 tw-institutional-strategy 所需的 GitHub Labels
# 執行前請先確保已登入 gh CLI 並位於正確的 repo 目錄
set -euo pipefail

# 策略標籤（藍色系）
gh label create "setup-a" --color "0075ca" --description "Setup A strategy candidate" || true
gh label create "setup-b" --color "0052cc" --description "Setup B strategy candidate" || true
gh label create "setup-c" --color "003d99" --description "Setup C strategy candidate" || true

# 狀態標籤（灰→綠色系）
gh label create "screened" --color "e4e669" --description "Passed initial screening" || true
gh label create "signal-confirmed" --color "0e8a16" --description "Signal confirmed, ready to enter" || true
gh label create "holding" --color "006b75" --description "Position is being held" || true
gh label create "exit-triggered" --color "d93f0b" --description "Exit signal triggered" || true
gh label create "closed" --color "eeeeee" --description "Position closed" || true

# 風險標籤
gh label create "auto-ok" --color "0e8a16" --description "Passed automated guardrails" || true
gh label create "human-review" --color "d93f0b" --description "Needs manual human review" || true
gh label create "data-missing" --color "e4e669" --description "Missing or incomplete data" || true
gh label create "guardrail-blocked" --color "b60205" --description "Blocked by guardrail rules" || true

# 結果標籤
gh label create "result-profit" --color "0e8a16" --description "Closed with profit" || true
gh label create "result-loss" --color "d93f0b" --description "Closed with loss" || true
gh label create "result-time-exit" --color "cccccc" --description "Closed by time-based exit" || true
gh label create "result-stoploss-hit" --color "b60205" --description "Closed by stop loss hit" || true

echo "Labels created (or already existed)."
