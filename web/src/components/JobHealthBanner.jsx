/* 排程健康橫幅（2026-09-17 架構體檢 B4）。

   要解決的具體事故：2026-09-13、09-14 兩天 TPEx 與興櫃資料源連線失敗，
   market_scan 照樣「完成」，掃描檔數從 2327 掉到 1074——等於那兩天的
   選股結果少了一半以上的標的，而 PO 是三天後做架構體檢才發現。錯誤
   一直記在資料庫欄位裡，只是沒有任何地方會顯示它。

   只在 critical／warning 時顯示。ok 與 unknown（巡檢還沒跑過）都不佔
   版面——常駐的綠色「一切正常」橫幅會訓練人忽略這個位置，等真的變紅
   的那天就看不見了。 */
export default function JobHealthBanner({ health }) {
  if (!health) return null
  const status = health.status
  if (status !== 'critical' && status !== 'warning') return null

  const problems = (health.findings || []).filter((f) => f.severity !== 'ok')
  return (
    <div className={'job-banner job-banner--' + status} role="status">
      <div className="job-banner__head">
        {status === 'critical' ? '排程出問題，資料可能不完整' : '排程有異常'}
        {health.checked_at && (
          <span className="job-banner__time">巡檢於 {health.checked_at.slice(0, 16).replace('T', ' ')}</span>
        )}
      </div>
      <ul className="job-banner__list">
        {problems.map((f, i) => (
          <li key={i}><b>{f.job}</b>：{f.detail}</li>
        ))}
      </ul>
    </div>
  )
}
