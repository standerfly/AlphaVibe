# Quickstart: Pending Verification List

給要動手實作（`/speckit.tasks` → `/speckit.implement`）或事後驗收這個
功能的人，一份最短路徑的手動驗證步驟。比照 `poc/kb-mcp/README.md`／
`CLAUDE.md`「常用查證點」既有的驗證方式，**一律用獨立測試資料庫，
絕對不要指向 `poc/data/`（正式庫）**。

## 1. 準備獨立測試資料庫

```bash
mkdir -p poc/data-test
export ALPHAVIBE_DATA_DIR=$(pwd)/poc/data-test
```

## 2. 資料層（`poc/kb-mcp/kb_store.py`）驗證

```bash
python3 -m unittest discover -s poc/kb-mcp/tests
```

新增的 `pending_verifications` 相關單元測試應涵蓋（見
`data-model.md`）：
- 登記成功、缺必填欄位被拒絕（含 `trigger_type=date` 卻缺
  `trigger_date` 的情境）
- 依 `status` 查詢、「已到期」查詢（含邊界：剛好等於7天窗口邊緣）
- `resolve` 需要 `resolution`（`status=resolved` 時）、`dropped` 時
  `resolution` 可選
- 終態不可逆：對已 `resolved`／`dropped` 的項目再次 `resolve` 應被拒絕

## 3. MCP tool 驗證（`poc/kb-mcp/server.py`）

比照既有工具，用 stdio 手動送一行 JSON-RPC 測試（或用既有的
MCP client 測試腳本，若 `poc/kb-mcp/tests/` 已有對應樣板則沿用）：

```bash
ALPHAVIBE_DATA_DIR=$(pwd)/poc/data-test python3 poc/kb-mcp/server.py
```

呼叫 `save_pending_verification`／`list_pending_verifications`／
`resolve_pending_verification`，確認回傳內容與 `contracts/mcp-tools.md`
一致。

## 4. STND（`app/`）驗證

```bash
ALPHAVIBE_DATA_DIR=$(pwd)/poc/data-test \
  .venv/bin/python3 -m app.tests.test_smoke
```

新增的測試案例應包含（比照 2026-08-22 教訓紀錄，`GAP` 是併發測試）：
- `GET /api/pending-verifications` 空清單回傳 `{"items": []}`
- 有已到期項目時正確回傳
- **併發測試**：至少 30 個併發 request 打 `GET
  /api/pending-verifications`，全數成功（不能只測依序單一請求）

## 5. 前端手動驗證

```bash
cd web && npm run dev
```

打開首頁，確認：
- 有已到期/即將到期項目時，新區塊正確顯示
- 沒有項目時，顯示空狀態文字而非報錯
- 手動讓後端 API 回傳錯誤（例如暫時關閉 server），確認首頁其餘區塊
  （dashboard／holdings）仍正常顯示，只有新區塊顯示錯誤提示

## 6. 端到端案例（呼應 spec.md 的 NVIDIA 案例）

1. 登記一筆 `trigger_type=date`、`trigger_date` 設為今天以前的日期（
   模擬「已到期」）的項目
2. 打開首頁，確認該項目出現在新區塊
3. 用 `resolve_pending_verification` 標記為 `resolved` 並附結論
4. 重新整理首頁，確認該項目不再出現在新區塊
5. 用 `get_pending_verification` 查詢該筆 `id`，確認結論與
   `resolved_at` 仍完整可查（沒有被刪除）

**驗收基準**：正是 `product-spec.md`／`spec.md` 反覆引用的 NVIDIA
案例——若這個端到端流程能跑通，就代表「財報公布後不用自己想起來查」
這個核心痛點已經被解決。
