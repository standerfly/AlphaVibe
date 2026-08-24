import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// AlphaVibe 前端骨架（Q-046 第5節 Step 3）：build 產出的 dist/ 由
// app/main.py 掛載服務（同源部署，不需要正式環境的 CORS 設定）。
// 這裡的 server.proxy 只影響 `npm run dev` 本機開發體驗，把 /api、/mcp
// 轉給本機跑在 8090 的 uvicorn（見 AlphaVibe/CLAUDE.md 啟動指令），
// production build（`vite build`）完全不受這段影響。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8090', changeOrigin: true },
      '/mcp': { target: 'http://127.0.0.1:8090', changeOrigin: true },
    },
  },
})
