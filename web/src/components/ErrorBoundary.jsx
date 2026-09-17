import React from 'react'

/* 錯誤邊界（2026-09-17 架構體檢 B3）。

   在這之前全 24 個前端檔案沒有任何 error boundary：頁面元件深度解構後端
   回應（例如 StockDetail 直接取多層欄位），後端結構一有落差就會讓整棵
   React 樹卸載——手機上看到的是全白畫面，沒有任何線索可循，也沒辦法
   靠切換分頁救回來。

   兩個實作重點：
   1. 這必須是 class component。React 只透過 componentDidCatch／
      getDerivedStateFromError 這兩個 class-only 生命週期回報渲染錯誤，
      hook 沒有對應 API（2026 年的 React 19 仍是如此）。
   2. 呼叫端要用 key={pathname} 掛載（見 AppShell.jsx）。error boundary
      的 state 不會自己清掉，沒有 key 的話使用者一旦踩到錯誤，切到其他
      分頁仍然停在錯誤畫面——反而比白畫面更像壞掉。key 變動會讓 React
      重建整個 boundary，state 跟著重置。 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // 留給開發者查的痕跡：手機上打不開 devtools，但至少接上電腦看得到
    console.error('[STND] 頁面渲染失敗：', error, info?.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="error-boundary">
        <h2 className="error-boundary__title">這個頁面載入時出錯了</h2>
        <p className="error-boundary__hint">
          其他分頁還能正常使用，可以先切過去。如果重新整理後還是這樣，
          把下面的錯誤訊息一起回報會比較好查。
        </p>
        <div className="error-boundary__actions">
          <button className="btn" onClick={() => window.location.reload()}>
            重新整理
          </button>
          <button className="btn-muted" onClick={() => { window.location.href = '/' }}>
            回首頁
          </button>
        </div>
        <details className="error-boundary__details">
          <summary>錯誤訊息</summary>
          <pre>{String(error?.stack || error)}</pre>
        </details>
      </div>
    )
  }
}
