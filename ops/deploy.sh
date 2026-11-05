#!/bin/bash
# STND 正式環境部署（2026-10-29）。
#
# 正式服務與 8 個排程跑在獨立的 git worktree `AlphaVibe-prod`（detached HEAD，
# 只放正式版程式），開發資料夾 `AlphaVibe` 怎麼切分支都不影響正式環境。
# 資料庫不在 worktree 裡：`AlphaVibe-prod/poc/data` 是指向
# `AlphaVibe/poc/data` 的 symlink。架構說明見 docs/architecture.md「部署與存取」。
#
# 用法（一律從 GitHub 上最新版取腳本執行，這樣回滾到沒有這支腳本的舊版也能用）：
#   cd /Users/stander/My_project/AlphaVibe-prod && git fetch origin function/alphavibe \
#     && bash <(git show origin/function/alphavibe:ops/deploy.sh)            部署最新版
#   …同上… bash <(git show origin/function/alphavibe:ops/deploy.sh) <commit> 部署指定版本（回滾）
#
# 只重新建置有變動的部分：app/requirements.txt 變了才 pip install、web/ 變了才
# 重建前端、scraper 的 package 檔變了才 npm ci。排程（marketscan 等）每次執行時
# 才讀程式檔，不需要重新載入；只重啟常駐的 reportserver。
#
# macOS 內建 bash 3.2 相容；請用 bash 執行（zsh 的變數展開規則不同）。
set -euo pipefail

PROD=${ALPHAVIBE_PROD_DIR:-/Users/stander/My_project/AlphaVibe-prod}  # 環境變數只供測試覆寫
LABEL=com.alphavibe.reportserver

cd "$PROD"

# 正式資料夾不該有人手改程式；有的話先停下來查清楚，不要覆蓋掉。
# （poc/data 是 symlink，屬未追蹤檔案，--untracked-files=no 不會把它算進來）
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "中止：$PROD 有未提交的修改，先查清楚是什麼：" >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

git fetch origin function/alphavibe
OLD=$(git rev-parse HEAD)
NEW=$(git rev-parse "${1:-origin/function/alphavibe}")

if [ "$OLD" = "$NEW" ]; then
  echo "已是這個版本：$(git log --oneline -1 "$NEW")"
  exit 0
fi

echo "部署：$(git log --oneline -1 "$OLD")"
echo "   → $(git log --oneline -1 "$NEW")"
git checkout --quiet --detach "$NEW"

CHANGED=$(git diff --name-only "$OLD" "$NEW")
if echo "$CHANGED" | grep -q '^app/requirements\.txt$'; then
  echo "app/requirements.txt 有變動，更新 Python 套件…"
  .venv/bin/pip install -r app/requirements.txt
fi
if echo "$CHANGED" | grep -q '^web/'; then
  echo "web/ 有變動，重新建置前端…"
  (cd web && npm ci && npm run build)
fi
if echo "$CHANGED" | grep -q '^poc/kb-mcp/scraper/package'; then
  echo "scraper 套件有變動，重新安裝…"
  (cd poc/kb-mcp/scraper && npm ci)
fi

# 用 kickstart -k 重啟（不要 bootout + bootstrap：常駐服務還沒關完就 bootstrap
# 會失敗成「Bootstrap failed: 5」，服務直接停擺——2026-10-29 實際踩到）。
launchctl kickstart -k "gui/$(id -u)/$LABEL"
sleep 5

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8080/mcp/wrong || true)
if [ "$CODE" = "404" ]; then
  echo "完成：服務已用新版本重啟（健康檢查 404＝正常）。"
  echo "要回滾：cd $PROD && bash <(git show origin/function/alphavibe:ops/deploy.sh) $OLD"
else
  echo "警告：重啟後健康檢查回 $CODE（預期 404），請看 ~/Library/Logs/alphavibe-report-server.err.log" >&2
  echo "要回滾：cd $PROD && bash <(git show origin/function/alphavibe:ops/deploy.sh) $OLD" >&2
  exit 1
fi
