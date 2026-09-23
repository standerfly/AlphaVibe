/* 機票掃描分頁（specs/005-flight-scan-page）。

   核心概念：**日期是輸出不是輸入**——使用者只給目的地、候選外站、出發
   區間與行程天數，系統在區間內抽樣日期並查價，回傳依價格排序的組合。

   本檔案目前是骨架（T011）。條件卡片、結果表與表單於 US1（T021–T024）
   實作。 */
import { useEffect, useState } from 'react'
import { apiGet } from '../api/client.js'

export default function Flights() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    apiGet('/api/flights/healthz')
      .then((d) => { if (alive) setHealth(d) })
      .catch((e) => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [])

  return (
    <section className="page">
      <h1>機票</h1>
      <p className="page__lead">
        外站四段票掃描。給定目的地、候選外站與出發區間，系統抽樣日期查價，
        回傳依價格排序的組合——不需要自己指定日期。
      </p>
      {error && <p className="error">載入失敗：{error}</p>}
      {health && (
        <p className="muted">
          資料層就緒（{health.db}），目前有 {health.tracks} 個查詢條件。
        </p>
      )}
    </section>
  )
}
