#!/bin/bash
# mac-amos-check.sh — macOS 資訊竊取木馬（AMOS / Atomic Stealer 類）唯讀健檢
#
# 用途：比對公開報告中的入侵指標（IOC），找出可疑的隱藏檔、開機常駐項目、
#       可疑下載來源與高風險指令紀錄。
# 原則：**完全唯讀**——不刪除、不搬移、不執行任何可疑檔案，不需 sudo，不連網。
# 用法：bash ops/security/mac-amos-check.sh 2>&1 | tee ~/Desktop/amos-check-$(date +%Y%m%d).txt
#       建議先斷網再執行；有命中時「不要」自己雙擊或 cat 可疑二進位檔。
# 相容：macOS 內建 bash 3.2。
set -u

HITS=0
hit()  { HITS=$((HITS+1)); printf '  [!] %s\n' "$*"; }
info() { printf '  [-] %s\n' "$*"; }
sec()  { printf '\n== %s ==\n' "$*"; }

# 本 repo 自己的常駐服務與 Apple 名稱：只用來「標註」，不跳過內容檢查
# （木馬常冒用 com.apple.* 名稱；真正的 Apple 常駐項目在 /System/Library，
#  出現在下面三個目錄的 com.apple.* 本身就可疑）
KNOWN_LABEL_RE='^com\.alphavibe\.'
APPLE_LABEL_RE='^com\.apple\.'

# 從 URL 取出小寫網域（去掉 scheme、帳密、埠號、路徑）
url_host() {
  printf '%s' "$1" | sed -E 's#^[a-zA-Z][a-zA-Z0-9+.-]*://##; s#[/?\#].*$##; s#^.*@##; s#:[0-9]+$##' \
    | tr 'A-Z' 'a-z'
}
# 網域本身或其子網域屬於官方白名單
official_host() {
  case "$1" in
    anthropic.com|*.anthropic.com|claude.ai|*.claude.ai|claude.com|*.claude.com) return 0;;
    apple.com|*.apple.com|brew.sh|*.brew.sh|python.org|*.python.org) return 0;;
    nodejs.org|*.nodejs.org|ngrok.com|*.ngrok.com|microsoft.com|*.microsoft.com) return 0;;
  esac
  return 1
}
# GitHub 只信任 Anthropic 與 Homebrew 的官方組織
official_github() {
  case "$1" in
    https://github.com/anthropics/*|https://github.com/Homebrew/*) return 0;;
    https://raw.githubusercontent.com/anthropics/*|https://raw.githubusercontent.com/Homebrew/*) return 0;;
  esac
  return 1
}
official_url() {
  official_host "$(url_host "$1")" && return 0
  official_github "$1"
}

sec "1. 已知 AMOS 入侵指標檔案"
for f in "$HOME/.mainhelper" "$HOME/.pass" "$HOME/.id" "$HOME/.agent" \
         "$HOME/.helper" "$HOME/.username" "$HOME/.mainHelper" \
         /Library/LaunchDaemons/com.finder.helper.plist \
         "$HOME/Library/LaunchAgents/com.finder.helper.plist" \
         /Library/LaunchAgents/com.finder.helper.plist; do
  if [ -e "$f" ]; then
    hit "存在：${f}（建立時間：$(stat -f '%SB' "$f" 2>/dev/null)）"
  fi
done
[ "$HITS" -eq 0 ] && info "未發現已知 IOC 檔案"

sec "2. 家目錄根層的隱藏可執行檔／二進位檔"
for f in "$HOME"/.[!.]*; do
  [ -f "$f" ] || continue
  kind=$(file -b "$f" 2>/dev/null)
  case "$kind" in
    *Mach-O*) hit "Mach-O 執行檔：$f ($kind)";;
    *) if [ -x "$f" ]; then
         case "$(basename "$f")" in
           .zshrc|.bashrc|.bash_profile|.profile|.zprofile|.zshenv) ;;
           *) hit "具執行權限的隱藏檔：$f ($kind)";;
         esac
       fi;;
  esac
done

sec "3. 開機常駐項目（LaunchAgents / LaunchDaemons）"
for dir in "$HOME/Library/LaunchAgents" /Library/LaunchAgents /Library/LaunchDaemons; do
  [ -d "$dir" ] || continue
  for p in "$dir"/*.plist; do
    [ -f "$p" ] || continue
    label=$(basename "$p" .plist)
    args=$(plutil -extract ProgramArguments json -o - "$p" 2>/dev/null \
           || plutil -extract Program raw -o - "$p" 2>/dev/null || echo "?")
    # plutil 的 JSON 會把 / 轉義成 \/，不還原的話下面的路徑比對永遠不會命中
    args=$(printf '%s' "$args" | sed 's#\\/#/#g')
    tag=""
    if echo "$label" | grep -Eq "$KNOWN_LABEL_RE"; then
      tag="白名單名稱"
    elif echo "$label" | grep -Eq "$APPLE_LABEL_RE"; then
      hit "冒用 Apple 名稱（不在 /System/Library）：$p → $args"
      continue
    fi
    if echo "$args" | grep -Eq "$HOME/\.|/Users/[^/\"]+/\.|/tmp/|/private/tmp|osascript|curl|base64|/bin/(ba|z)?sh\""; then
      if [ -n "$tag" ]; then
        hit "白名單名稱但內容可疑：$p → $args"
      else
        hit "可疑：$p → $args"
      fi
    elif [ -n "$tag" ]; then
      info "已知（${tag}，內容已檢查）：$label → $args"
    else
      info "$label → $args"
    fi
  done
done

sec "4. 正在執行、路徑落在家目錄隱藏檔或 /tmp 的行程"
while read -r line; do hit "行程：$line"; done < <(
  ps -axo pid=,command= | grep -E "$HOME/\.[^/ ]+( |$)|/tmp/|/private/tmp/" \
  | grep -vE 'grep|\.vscode|\.cursor|\.claude|\.local/bin|\.nvm|\.pyenv|\.cargo|\.npm|\.bun|\.docker|\.ollama')

sec "5. 下載來源紀錄（Gatekeeper 隔離資料庫，近 400 筆）"
QDB=$(ls "$HOME"/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV* 2>/dev/null | head -1)
if [ -n "$QDB" ] && command -v sqlite3 >/dev/null; then
  TAB=$(printf '\t')
  while IFS="$TAB" read -r ts agent url origin; do
    printf '%s %s' "$url" "$origin" | grep -iqE 'claude|anthropic|\.dmg|\.pkg|install|\.sh([?#]|$)' || continue
    official_url "$url" && continue
    hit "非官方來源下載：$ts $agent ${url}（來源頁：${origin:-無}）"
  done < <(
  sqlite3 -separator "$TAB" "$QDB" "SELECT datetime(LSQuarantineTimeStamp+978307200,'unixepoch','localtime'),
                         IFNULL(LSQuarantineAgentName,''), IFNULL(LSQuarantineDataURLString,''),
                         IFNULL(LSQuarantineOriginURLString,'')
                  FROM LSQuarantineEvent ORDER BY LSQuarantineTimeStamp DESC LIMIT 400;" 2>/dev/null)
  info "（只列出與 claude/安裝檔相關、且網域不在官方白名單的下載；GitHub 只信任 anthropics／Homebrew 組織）"
else
  info "讀不到隔離資料庫（可能被清空或權限不足）"
fi

sec "6. Claude Code 安裝來源"
for c in $(which -a claude 2>/dev/null); do
  real=$(readlink "$c" 2>/dev/null || echo "$c")
  info "claude → $c ($real)"
done
[ -z "$(which -a claude 2>/dev/null)" ] && info "PATH 中找不到 claude"
info "官方安裝來源只有：claude.ai/install.sh、npm @anthropic-ai/claude-code、Homebrew cask claude-code"

sec "7. Shell 歷史中的高風險指令（curl|bash、base64 解碼、osascript 密碼框）"
for h in "$HOME/.zsh_history" "$HOME/.bash_history"; do
  [ -f "$h" ] || continue
  shown=0
  while read -r line; do
    # 只有「含網址且每個網址都屬官方網域」的指令才排除；以網域比對，不比子字串
    urls=$(printf '%s\n' "$line" | grep -oE "https?://[^[:space:]|\"')]+")
    if [ -n "$urls" ]; then
      all_official=1
      for u in $urls; do official_url "$u" || { all_official=0; break; }; done
      [ "$all_official" -eq 1 ] && continue
    fi
    shown=$((shown+1))
    [ "$shown" -le 20 ] && hit "$(basename "$h"):$line"
  done < <(
  LC_ALL=C grep -naE '(curl|wget)[^|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba|z)?sh|base64[[:space:]]+(-d|--decode)|osascript.*(password|display dialog)|xattr[[:space:]]+-(c|d)' "$h" 2>/dev/null)
  [ "$shown" -gt 20 ] && info "$(basename "$h") 另有 $((shown-20)) 筆命中未逐條列出（未計入命中數），請人工檢查"
done

sec "8. 系統防護狀態"
info "Gatekeeper：$(spctl --status 2>/dev/null)"
info "SIP：$(csrutil status 2>/dev/null)"
info "XProtect 版本：$(defaults read /Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist CFBundleShortVersionString 2>/dev/null || echo '?')"

sec "結果"
if [ "$HITS" -gt 0 ]; then
  echo "  共 $HITS 項需人工確認。若第 1 節有命中：視為已中毒——先斷網，"
  echo "  改用『另一台乾淨裝置』執行 ops/security/README.md 的「中毒後處置」。"
else
  echo "  未發現已知指標。這不保證乾淨，仍建議用 Malwarebytes / Avast 全機掃描一次。"
fi
