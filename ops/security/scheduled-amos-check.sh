#!/bin/bash
# scheduled-amos-check.sh — 由 launchd 每週執行 mac-amos-check.sh 的包裝腳本
#
# 做三件事：
#   1. 跑健檢，完整報告存 ~/Library/Logs/amos-check/（權限 600，保留最近 26 份）
#   2. 跟上一份報告比對，算出「新增」的命中項目
#   3. 發 macOS 通知＋Telegram 摘要——**只送數字，不送細節**：報告可能含
#      shell 歷史，不能離開這台機器；細節請到報告檔看
# 排程設定：ops/launchd/com.alphavibe.amoscheck.plist
# 手動測試：bash ops/security/scheduled-amos-check.sh
set -u

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$HOME/Library/Logs/amos-check"
KEEP=26
mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

PREV=$(ls -1 "$OUT_DIR"/amos-check-*.txt 2>/dev/null | tail -1)
REPORT="$OUT_DIR/amos-check-$(date +%Y%m%d-%H%M%S).txt"
( umask 077; /bin/bash "$REPO/ops/security/mac-amos-check.sh" > "$REPORT" 2>&1 )
rc=$?

# 每一行命中加上所屬節號，方便分節統計與跨週比對
hits_of() {
  LC_ALL=C awk '/^== [0-9]/{s=$2; sub(/\..*/,"",s)} /\[!\]/ && s!="4" {print s "\t" $0}' "$1" | sort -u
}
# 第 4 節（執行中行程）每次 PID 都不同，跨週比對會一直算成新增，另外計數
proc_hits() { LC_ALL=C awk '/^== [0-9]/{s=$2; sub(/\..*/,"",s)} /\[!\]/ && s=="4" {c++} END{print c+0}' "$1"; }

CUR_HITS=$(hits_of "$REPORT")
total=$(printf '%s' "$CUR_HITS" | grep -c . )
procs=$(proc_hits "$REPORT")
total=$((total + procs))
sec1=$(printf '%s\n' "$CUR_HITS" | grep -c $'^1\t')
if [ -n "$PREV" ]; then
  new=$(comm -13 <(hits_of "$PREV") <(printf '%s\n' "$CUR_HITS" | grep .) | grep -c .)
else
  new=$total
fi
crashed=0
LC_ALL=C grep -q '^== 結果' "$REPORT" || crashed=1

if [ "$crashed" -eq 1 ]; then
  level="⚠️ 健檢腳本沒有跑完（exit ${rc}）"
elif [ "$sec1" -gt 0 ]; then
  level="🚨 第 1 節命中已知 AMOS 指標 $sec1 項：視為已中毒，先斷網，改用另一台裝置處置"
elif [ "$new" -gt 0 ] || [ "$procs" -gt 0 ]; then
  level="⚠️ 有新增項目需要人工確認"
else
  level="✅ 沒有新增項目"
fi
summary="AMOS 週健檢（$(hostname -s)）
$level
命中 $total 項，比上次新增 $new 項，可疑行程 $procs 項
報告：~/Library/Logs/amos-check/$(basename "$REPORT")"

echo "$summary"

# macOS 通知（失敗不影響其他步驟）
osascript -e "display notification \"命中 $total 項，新增 $new 項\" with title \"AMOS 週健檢\" subtitle \"$(printf '%s' "$level" | tr -d '"')\"" >/dev/null 2>&1 || true

# Telegram 摘要：沿用 poc/kb-mcp/notify.py（它保證失敗不拋例外）
# 一週只發一次，偶發的 SSL 握手逾時（2026-11-05 實測遇過）不該讓這週的結果漏掉，失敗就隔 30 秒重送一次
if ! /usr/bin/python3 "$REPO/poc/kb-mcp/notify.py" "$summary"; then
  sleep 30
  /usr/bin/python3 "$REPO/poc/kb-mcp/notify.py" "$summary" || echo "Telegram 重送仍失敗，請看報告檔"
fi

# 只保留最近 KEEP 份報告
count=$(ls -1 "$OUT_DIR"/amos-check-*.txt 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt "$KEEP" ]; then
  ls -1 "$OUT_DIR"/amos-check-*.txt | head -n $((count - KEEP)) | while read -r old; do rm -f "$old"; done
fi
exit 0
