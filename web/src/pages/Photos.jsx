import { PhotosIcon, UploadIcon } from '../components/icons.jsx'

/* 相簿分頁：規劃文件定案的 MVP 設計——「MVP 階段僅做導覽入口，不含任何
   功能」，完整功能（AutoGallery 資料模型遷移、X3F 轉檔混合模式）延後到
   架構重寫、資產分頁都完成後才開工（見 Q-046 supporting-artifacts
   「相簿分頁設計」節）。不接任何 API，「上傳照片」按鈕維持禁用態。 */
export default function Photos() {
  return (
    <div>
      <div className="page-title"><h1>相簿</h1></div>
      <div className="placeholder-box">
        <div className="placeholder-box__icon"><PhotosIcon width={56} height={56} /></div>
        <div className="placeholder-box__title">相簿功能開發中</div>
        <div className="placeholder-box__text">
          等資產分頁與其他工作完成後才開工。完整功能規劃包含既有 AutoGallery
          資料模型遷移（去重、rating、拍攝日期、標籤）與 Sigma X3F 檔案轉檔流程。
        </div>
        <div style={{ marginTop: '1.2rem' }}>
          <button type="button" className="btn" disabled>
            <UploadIcon width={16} height={16} style={{ verticalAlign: '-3px', marginRight: '.35rem' }} />
            上傳照片（尚未開放）
          </button>
        </div>
      </div>
    </div>
  )
}
