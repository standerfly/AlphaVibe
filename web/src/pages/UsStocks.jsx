import { UsStocksIcon } from '../components/icons.jsx'

/* 美股分頁 landing 頁佔位版本（Phase 1 骨架，比照 Photos.jsx 的
   placeholder-box 模式）。完整版（持股清單＋現價＋漲跌＋立場/監控狀態）
   是 specs/003-us-stocks/tasks.md T019/T030 的工作範圍，這裡先只證明
   路由/導覽列掛載正確。

   美股功能與既有台股系統在分頁/資料表/查詢管道三層完全獨立
   （FR-015/016，見 specs/003-us-stocks/research.md §1/2）——這個頁面
   之後串接的是 app/routers/us_stocks.py 的獨立 API，不會呼叫任何既有
   台股 /api/dashboard、/api/screen 等端點。 */
export default function UsStocks() {
  return (
    <div>
      <div className="page-title"><h1>美股</h1></div>
      <div className="placeholder-box">
        <div className="placeholder-box__icon"><UsStocksIcon width={56} height={56} /></div>
        <div className="placeholder-box__title">美股功能開發中</div>
        <div className="placeholder-box__text">
          美股獨立投資系統的地基已完成（獨立資料庫、獨立查詢管道，跟台股
          完全分開）。完整功能——交易截圖匯入、股價走勢圖疊加買賣點位、
          研究筆記與投資立場記錄、關注條件監控推播——陸續開發中。
        </div>
      </div>
    </div>
  )
}
