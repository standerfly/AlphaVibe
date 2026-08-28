"""待觀察／待查詢清單：唯讀查詢 API，供 STND 首頁顯示用。

登記（save）與標記解決（resolve）一律透過 `poc/kb-mcp/server.py` 的
MCP tool 完成，不在這裡提供對應的 POST/PATCH endpoint——這是 pre-spec
Q-003a 的明確決定（首頁區塊純顯示，不做就地操作），見
`specs/001-pending-verification-list/contracts/http-api.md`「範圍說明」
一節。這裡只服務首頁「已到期／即將到期」清單這一個查詢需求，跟其他
router 一樣直接呼叫 `poc/kb-mcp/kb_store.py` 既有方法，不重寫商業邏輯。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.deps import KBStore, get_kb_store

router = APIRouter()


@router.get("/api/pending-verifications")
def list_pending_verifications(
    due_only: bool = Query(
        True, description="true 時只回傳已到期/即將到期(7天內)且status=pending的項目"
    ),
    status: Optional[str] = Query(
        None, description="依狀態篩選；與 due_only=true 併用時被忽略"
    ),
    store: KBStore = Depends(get_kb_store),
) -> Dict[str, Any]:
    if due_only:
        items = store.list_pending_verifications(due_only=True)
    else:
        items = store.list_pending_verifications(status=status)
    return {"items": items}
