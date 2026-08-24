/* 主題切換（2026-08-22 新增）：三態循環「跟隨系統 → 淺色 → 深色 →
   跟隨系統」，存在 localStorage，套用方式是在 <html> 上設
   data-theme="light"／"dark"（跟隨系統時移除這個屬性，讓
   tokens.css 的 @media (prefers-color-scheme) 生效）。

   index.html 有一段 inline script 在 React 掛載前就先套用一次存好的
   選擇，避免深色模式使用者一開始先閃一下淺色畫面（flash of wrong
   theme）——這個檔案裡的邏輯要跟那段 inline script 保持一致，改動
   其中一邊記得同步另一邊。 */

const STORAGE_KEY = 'alphavibe-theme'
const THEMES = ['system', 'light', 'dark']

export function getStoredTheme() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return THEMES.includes(v) ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme) {
  const root = document.documentElement
  if (theme === 'light' || theme === 'dark') {
    root.dataset.theme = theme
  } else {
    delete root.dataset.theme
  }
}

export function setTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    /* localStorage 不可用（例如無痕模式）時，退化成只在當前分頁
       套用，不持久化——不讓例外中斷切換動作本身。 */
  }
  applyTheme(theme)
}

export function nextTheme(current) {
  const i = THEMES.indexOf(current)
  return THEMES[(i + 1) % THEMES.length]
}
