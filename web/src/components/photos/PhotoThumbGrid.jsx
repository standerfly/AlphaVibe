import { PhotosIcon } from '../icons.jsx'

/* 2026-09-30 新增：相簿頁與全域搜尋頁共用的縮圖格——兩邊原本各自
   inline 一份幾乎一樣的縮圖+多選+評分邏輯，現在拆成共用元件，避免
   之後改其中一邊忘了同步另一邊（跟 MacBook Air／Mac mini 版本同步
   同一種「兩份要手動保持一致」風險，能消掉就消掉）。

   PO 的「像膠片時代 contact sheet 選片」需求裡，最在乎的兩點：
   (1) 不用進詳情頁、直接在縮圖上標記好壞（速度）
   (2) 先把既有的多選＋批次工具列模式搬過去就好，之後再迭代
   這裡把兩者結合：縮圖本身就有可以直接點的星等（單張立即生效，走
   PATCH /api/photos/photos/{id}，不需要先多選），多選＋批次工具列
   （AlbumDetail.jsx／SearchPanel.jsx 各自的 photo-toolbar）留給呼叫端
   處理，這個元件只管縮圖格本身。 */
export default function PhotoThumbGrid({ photos, selected, onToggleSelect, onOpenDetail, onQuickRate }) {
  return (
    <div className="thumb-grid">
      {photos.map((photo) => (
        <button
          key={photo.id}
          className={`thumb${selected?.has(photo.id) ? ' is-selected' : ''}`}
          onClick={() => onToggleSelect(photo.id)}
          onDoubleClick={() => onOpenDetail(photo.id)}
          title="點一下多選；點兩下看詳情"
        >
          <img src={`/api/photos/thumbnail/${photo.id}`} alt=""
            onError={(e) => { e.target.style.display = 'none' }} />
          <PhotosIcon width={22} height={22}
            style={{ position: 'absolute', top: '50%', left: '50%',
              transform: 'translate(-50%,-50%)', opacity: .35 }} />
          <span
            className="thumb__quickrate"
            onClick={(e) => e.stopPropagation()}
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <span
                key={n}
                role="button"
                aria-label={`評 ${n} 星`}
                onClick={(e) => {
                  e.stopPropagation()
                  // 點目前已經是的那顆星＝取消評分（設回 0），比照一般
                  // 星等控制的慣例，讓使用者也能反悔清空。
                  onQuickRate(photo.id, n === photo.rating ? 0 : n)
                }}
              >
                {n <= (photo.rating || 0) ? '★' : '☆'}
              </span>
            ))}
          </span>
          <span
            role="button"
            onClick={(e) => { e.stopPropagation(); onOpenDetail(photo.id) }}
            className="thumb__detail-link"
          >
            詳情
          </span>
        </button>
      ))}
    </div>
  )
}
