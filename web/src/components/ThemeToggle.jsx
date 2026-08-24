import { useState } from 'react'
import { SunIcon, MoonIcon, SystemIcon } from './icons.jsx'
import { getStoredTheme, setTheme, nextTheme } from '../theme.js'

const META = {
  system: { Icon: SystemIcon, label: '跟隨系統' },
  light: { Icon: SunIcon, label: '淺色' },
  dark: { Icon: MoonIcon, label: '深色' },
}

/* 三態循環按鈕，放在 topnav 右側。點一下切到下一態並立刻套用＋存檔
   （見 theme.js），不用另外開選單——單人使用的工具，循環比下拉選單
   更少點擊次數。 */
export default function ThemeToggle() {
  const [theme, setThemeState] = useState(getStoredTheme)

  function handleClick() {
    const next = nextTheme(theme)
    setTheme(next)
    setThemeState(next)
  }

  const { Icon, label } = META[theme]
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={handleClick}
      title={`目前：${label}（點擊切換）`}
      aria-label={`主題：${label}，點擊切換`}
    >
      <Icon />
    </button>
  )
}
