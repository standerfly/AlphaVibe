/* 美股「完整研究筆記」渲染元件（Phase 4 US2，T023）。

   `fullNote` 是 Markdown 純文字（見 data-model.md `us_stances.full_note`
   欄位說明），這裡把它轉成排版好的 HTML/JSX 呈現在個股詳情頁的「投資
   立場」卡片展開區（UsStockDetail.jsx，T024）。

   **FR-009 硬性要求：呈現時不得因版面密度考量而省略或壓縮內容**——
   這是 2026-09-04 對話中 PO 明確否決過「把 7 節內容壓縮成 5 張卡片」
   方案的地方（見 specs/003-us-stocks/spec.md FR-009 與 tasks.md T023
   註記）。本元件因此刻意設計成「逐行掃描 fullNote 的每一行、每一行都
   歸進某個區塊」的解析器（parseBlocks，狀態機風格，比照
   poc/kb-mcp/us_trade_text_parser.py 的逐行解析慣例）——沒有任何「只取
   前 N 字」「只顯示摘要」的邏輯，也沒有任何區塊類型被丟棄不渲染，任何
   一行文字最終都會落在某個 block 裡被 renderBlock 畫出來。

   **技術取捨：不新增 npm 依賴**（不用 react-markdown 之類的套件）——
   `web/package.json` 目前只有 3 個直接依賴（react/react-dom/
   react-router-dom），這裡改寫一份輕量、涵蓋研究筆記實際會用到語法的
   解析器：標題（# ~ ######）、段落、無序/有序清單、表格、引用
   （blockquote）、分隔線（---）、行內粗體/連結/code。涵蓋範圍以
   `docs/research/2026-09-04-cloudflare-net-outlook.md` 這類真實研究
   筆記樣本的全部語法為準（見該檔案，Phase 4 規劃時的參考範例）；不支援
   的語法（例如巢狀清單、斜體、圖片）會被當成一般段落原樣顯示文字，不會
   讓內容整段消失——「解析不到就當純文字保留」是這裡唯一的降級策略，跟
   「省略/壓縮」是兩回事。 */

function renderInline(text, keyPrefix) {
  const nodes = []
  const re = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g
  let last = 0
  let match
  let idx = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    if (match[1] !== undefined) {
      nodes.push(<strong key={`${keyPrefix}-${idx++}`}>{match[1]}</strong>)
    } else if (match[2] !== undefined) {
      nodes.push(<code key={`${keyPrefix}-${idx++}`}>{match[2]}</code>)
    } else {
      nodes.push(
        <a key={`${keyPrefix}-${idx++}`} href={match[4]} target="_blank" rel="noreferrer">
          {match[3]}
        </a>,
      )
    }
    last = re.lastIndex
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

const HEADING_RE = /^(#{1,6})\s+(.*)$/
const HR_RE = /^-{3,}\s*$/
const TABLE_ROW_RE = /^\|.*\|\s*$/
const TABLE_SEP_RE = /^\|?[\s:|-]+\|?\s*$/
const QUOTE_RE = /^>\s?/
const UL_RE = /^[-*]\s+/
const OL_RE = /^\d+\.\s+/

function splitTableRow(line) {
  const cells = line.split('|').map((c) => c.trim())
  // 去掉開頭/結尾因 leading/trailing "|" 產生的空字串儲存格。
  if (cells.length && cells[0] === '') cells.shift()
  if (cells.length && cells[cells.length - 1] === '') cells.pop()
  return cells
}

/* 逐行掃描 fullNote，切成一串 block（每一行都會被某個 block 吃掉，不
   會被跳過）。刻意用 while 迴圈＋手動 index 遞增（而非 split('\n\n')
   之類的作法），因為清單/表格/引用內部本來就沒有空行分隔，用空行切段
   會把它們錯誤打散。 */
function parseBlocks(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    if (line.trim() === '') {
      i += 1
      continue
    }

    const heading = HEADING_RE.exec(line)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() })
      i += 1
      continue
    }

    if (HR_RE.test(line.trim())) {
      blocks.push({ type: 'hr' })
      i += 1
      continue
    }

    if (
      TABLE_ROW_RE.test(line) &&
      i + 1 < lines.length &&
      TABLE_SEP_RE.test(lines[i + 1]) &&
      lines[i + 1].includes('-')
    ) {
      const header = splitTableRow(line)
      const rows = []
      i += 2
      while (i < lines.length && TABLE_ROW_RE.test(lines[i])) {
        rows.push(splitTableRow(lines[i]))
        i += 1
      }
      blocks.push({ type: 'table', header, rows })
      continue
    }

    if (QUOTE_RE.test(line)) {
      const quoteLines = []
      while (i < lines.length && QUOTE_RE.test(lines[i])) {
        quoteLines.push(lines[i].replace(QUOTE_RE, ''))
        i += 1
      }
      blocks.push({ type: 'blockquote', lines: quoteLines })
      continue
    }

    if (UL_RE.test(line)) {
      const items = []
      while (i < lines.length && UL_RE.test(lines[i])) {
        items.push(lines[i].replace(UL_RE, ''))
        i += 1
      }
      blocks.push({ type: 'ul', items })
      continue
    }

    if (OL_RE.test(line)) {
      const items = []
      while (i < lines.length && OL_RE.test(lines[i])) {
        items.push(lines[i].replace(OL_RE, ''))
        i += 1
      }
      blocks.push({ type: 'ol', items })
      continue
    }

    // 一般段落：合併到下一個空行或下一個特殊區塊起始行為止，段落內部的
    // 手動換行渲染時保留為空白（同一段落的自然折行，非新段落）。
    const paraLines = [line]
    i += 1
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !HEADING_RE.test(lines[i]) &&
      !HR_RE.test(lines[i].trim()) &&
      !TABLE_ROW_RE.test(lines[i]) &&
      !QUOTE_RE.test(lines[i]) &&
      !UL_RE.test(lines[i]) &&
      !OL_RE.test(lines[i])
    ) {
      paraLines.push(lines[i])
      i += 1
    }
    blocks.push({ type: 'p', text: paraLines.join(' ') })
  }
  return blocks
}

function renderBlock(block, idx) {
  switch (block.type) {
    case 'heading': {
      // 筆記內部標題從 h3 開始（不是 h1/h2）——.card__head h2 已經是
      // 卡片本身的標題，筆記內部再出現 h1/h2 會跟卡片標題同層級混淆；
      // 不論來源是 # 或 ##，都對映到 h3 起跳，### 對映 h4，以此類推。
      const level = Math.min(Math.max(block.level, 1) + 2, 6)
      const Tag = `h${level}`
      return (
        <Tag className="us-note__heading" key={idx}>
          {renderInline(block.text, `h${idx}`)}
        </Tag>
      )
    }
    case 'hr':
      return <hr className="us-note__hr" key={idx} />
    case 'table':
      return (
        <div className="us-note__table-wrap" key={idx}>
          <table className="us-note__table">
            <thead>
              <tr>
                {block.header.map((cell, ci) => (
                  <th key={ci}>{renderInline(cell, `th${idx}-${ci}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td key={ci}>{renderInline(cell, `td${idx}-${ri}-${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'blockquote':
      return (
        <blockquote className="us-note__quote" key={idx}>
          {block.lines.map((l, li) => (
            <p key={li}>{renderInline(l, `bq${idx}-${li}`)}</p>
          ))}
        </blockquote>
      )
    case 'ul':
      return (
        <ul className="us-note__list" key={idx}>
          {block.items.map((it, ii) => (
            <li key={ii}>{renderInline(it, `ul${idx}-${ii}`)}</li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol className="us-note__list" key={idx}>
          {block.items.map((it, ii) => (
            <li key={ii}>{renderInline(it, `ol${idx}-${ii}`)}</li>
          ))}
        </ol>
      )
    case 'p':
    default:
      return (
        <p className="us-note__p" key={idx}>
          {renderInline(block.text, `p${idx}`)}
        </p>
      )
  }
}

/* `fullNote`：必填，Markdown 純文字。`title` 選填，元件本身不重複顯示
   direction/summary/價格帶（那些已經在 UsStockDetail.jsx 的「投資立場」
   卡片主體顯示，見 T024），這裡只負責 full_note 本文的完整呈現。 */
export default function UsStockResearchNote({ fullNote, title }) {
  if (!fullNote || !fullNote.trim()) {
    return <p className="empty">尚無研究筆記內容。</p>
  }
  const blocks = parseBlocks(fullNote)
  return (
    <article className="us-note">
      {title && <div className="us-note__title">{title}</div>}
      <div className="us-note__body">{blocks.map((b, i) => renderBlock(b, i))}</div>
    </article>
  )
}

// 供測試/除錯時直接檢查解析結果用（例如比對段落數量），不影響一般渲染
// 路徑，UsStockDetail.jsx 不需要也不應該 import 這個。
export { parseBlocks as __parseBlocksForTesting }
