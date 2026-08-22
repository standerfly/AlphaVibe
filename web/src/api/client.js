/* 極簡 fetch wrapper：同源部署（app/main.py 直接 mount dist/），相對路徑
   即可，不需要設定 API base URL。瀏覽器對同源請求預設就會帶 cookie
   （fetch 預設 credentials 是 "same-origin"），DashboardAuthMiddleware
   簽發的 session cookie 不需要額外設定就會自動帶上；未設定
   ALPHAVIBE_DASHBOARD_TOKEN 時中介層本來就 fail-open，401 只會在部署到
   公開網路且設定 token 後才可能出現，屆時瀏覽器會自己跳原生 Basic Auth
   對話框（不需要前端額外處理，見任務規格第6點）。 */

export class ApiError extends Error {
  constructor(message, status, path) {
    super(message)
    this.status = status
    this.path = path
  }
}

export async function apiGet(path) {
  const res = await fetch(path)
  if (!res.ok) {
    throw new ApiError(`${path} 回傳 ${res.status}`, res.status, path)
  }
  return res.json()
}

/* POST helper（資產分頁第一個用到寫入 API 的頁面，2026-08-21 新增）。
   `body` 省略時送出無 body 的 POST（例如 archive 端點不吃 request
   body，見 app/routers/assets.py 的 archive_pocket/archive_account）。
   失敗時盡量把後端 HTTPException 的 detail／Pydantic 422 錯誤內容帶進
   錯誤訊息，方便表單直接顯示給使用者看，不用只顯示「400」。 */
export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      if (data && data.detail) {
        detail = `：${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}`
      }
    } catch (_err) {
      // 回應不是 JSON（罕見），忽略，維持只有狀態碼的訊息。
    }
    throw new ApiError(`${path} 回傳 ${res.status}${detail}`, res.status, path)
  }
  return res.json()
}
