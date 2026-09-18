/* 極簡 fetch wrapper：同源部署（app/main.py 直接 mount dist/），相對路徑
   即可，不需要設定 API base URL。瀏覽器對同源請求預設就會帶 cookie
   （fetch 預設 credentials 是 "same-origin"），DashboardAuthMiddleware
   簽發的 session cookie 不需要額外設定就會自動帶上；未設定
   ALPHAVIBE_DASHBOARD_TOKEN 時中介層本來就 fail-open，401 只會在部署到
   公開網路且設定 token 後才可能出現，屆時瀏覽器會自己跳原生 Basic Auth
   對話框（不需要前端額外處理，見任務規格第6點）。 */

/* 2026-09-10 新增：對外網址是 ngrok 免費版 tunnel，瀏覽器 UA 的請求會被
   ngrok 攔截成它自己的「瀏覽器警告頁」（HTTP 200、Content-Type
   text/html，內容是 ngrok 的 HTML 而非我們的 API 回應）——不影響 curl
   等非瀏覽器 UA，只影響真實使用者。這個 header 是 ngrok 官方提供的
   繞過機制，值本身不檢查內容、只檢查存在與否；加在每個 fetch 上就能讓
   請求直接穿透到後端，不影響同源部署（非 ngrok 環境時後端會忽略這個
   header，無副作用）。實測見 clarification-log 對應教訓紀錄。 */
const NGROK_SKIP_HEADER = { 'ngrok-skip-browser-warning': 'true' }

export class ApiError extends Error {
  constructor(message, status, path) {
    super(message)
    this.status = status
    this.path = path
  }
}

export async function apiGet(path) {
  const res = await fetch(path, { headers: NGROK_SKIP_HEADER })
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
    headers: body !== undefined
      ? { ...NGROK_SKIP_HEADER, 'Content-Type': 'application/json' }
      : NGROK_SKIP_HEADER,
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

/* DELETE helper（Phase 5 US3 T029 第一次用到——監控條件卡片的刪除按鈕，
   `app/routers/us_stocks.py::remove_watch_condition`）。既有 Assets.jsx
   的「封存」動作是用 POST 到 /archive 端點模擬刪除，但監控條件是真的要
   移除整筆列（不是可回顧的歷史紀錄），用標準 DELETE 方法更直接對應
   語意，這裡補一個對稱於 apiPost 的極簡 helper，不強行套用 archive
   那套慣例。*/
export async function apiDelete(path) {
  const res = await fetch(path, { method: 'DELETE', headers: NGROK_SKIP_HEADER })
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      if (data && data.detail) {
        detail = `：${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}`
      }
    } catch (_err) {
      // 忽略非 JSON 回應。
    }
    throw new ApiError(`${path} 回傳 ${res.status}${detail}`, res.status, path)
  }
  return res.json()
}

/* PATCH helper（相簿分頁第一個用到，`app/routers/photos.py` 的
   album/photo 局部更新端點）。跟 apiPost 幾乎一樣，只是方法不同——
   PATCH 語意上是「局部更新」，跟 POST 的「建立/動作」分開，對應後端
   用 @router.patch 而非 @router.post 的端點。*/
export async function apiPatch(path, body) {
  const res = await fetch(path, {
    method: 'PATCH',
    headers: { ...NGROK_SKIP_HEADER, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      if (data && data.detail) {
        detail = `：${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}`
      }
    } catch (_err) {
      // 忽略非 JSON 回應。
    }
    throw new ApiError(`${path} 回傳 ${res.status}${detail}`, res.status, path)
  }
  return res.json()
}
