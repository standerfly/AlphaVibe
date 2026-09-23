/**
 * 外站四段票查價：以 headless Chromium 抓 Google Flights 多城市報價。
 *
 * 為什麼需要瀏覽器：Google Flights 的 SSR HTML 不含價格（2026-09-22 實測
 * 1.9MB 頁面裡找不到任何票價數字），價格由 JS 後續載入，curl/WebFetch
 * 拿不到。
 *
 * 用法（由 flight_search.py 呼叫，不手動執行）：
 *   echo '{"urls":[{"id":"NRT","url":"..."}]}' | node flight_scraper.js
 *
 * 輸出為 **JSON Lines**（每行一個 JSON 物件），逐筆即時寫出：
 *   {"type":"result", "id":..., "status":"ok", "price":...}   每查完一筆
 *   {"type":"summary","blocked":bool,"soft_blocked":bool,"stats":{...}}  最後一行
 * 逐筆輸出讓呼叫端能邊收邊落地快取——整批結束才回傳的話，中途當機或
 * 被中斷就會丟掉全部已完成的結果（168 筆完整掃描約 25 分鐘，風險不可接受）。
 * 所有進度訊息走 stderr，不污染 stdout。
 *
 * 節流依據（見 docs/research/2026-09-22-...md 第 12 節）：
 * Google robots.txt 未禁止 /travel/flights（只禁 /search、/s/、/booking），
 * 且無 Crawl-delay 指令；壓測 15 次、間隔 5–11 秒隨機，零封鎖。
 * 固定間隔本身就是機器人特徵，故用隨機區間。
 */
const { chromium } = require('playwright');
const fsp = require('fs');
const path = require('path');
const os = require('os');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rnd = (a, b) => a + Math.random() * (b - a);

/**
 * 找出可用的 chromium 執行檔。
 * playwright 套件版本與既有瀏覽器版本常不一致（套件要 1243、機器上是
 * 1217），直接 launch 會叫你重新下載 150MB。改成掃描 ms-playwright 快取
 * 取用既有的，避免下載。
 */
function findChromium() {
  // 優先序很重要：chrome-headless-shell 是**專用的 headless 二進位**，
  // 指紋極為明顯，2026-09-22 的掃描就是用它而在第 21 筆被 Google 擋下。
  // 完整的 Chrome 走新版 headless mode，指紋接近真實瀏覽器。
  // 系統安裝的 Google Chrome 最像真人，排最前面。
  const systemChrome =
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  if (fsp.existsSync(systemChrome)) return systemChrome;

  const base = path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright');
  if (!fsp.existsSync(base)) return null;
  const full = [];
  const shell = [];
  for (const dir of fsp.readdirSync(base)) {
    if (!/^chromium/.test(dir)) continue;
    for (const sub of [
      'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
      'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
    ]) {
      const p = path.join(base, dir, sub);
      if (fsp.existsSync(p)) full.push(p);
    }
    const sh = path.join(base, dir,
      'chrome-headless-shell-mac-arm64/chrome-headless-shell');
    if (fsp.existsSync(sh)) shell.push(sh);
  }
  full.sort().reverse();
  shell.sort().reverse();
  return full[0] || shell[0] || null;   // 完整 Chrome 優先，headless shell 墊底
}

// 注意：不能用 "recaptcha" 這類字串判定——Google 的**正常**航班頁面
// 裡就會出現 4 次（頁面 JS 引用 recaptcha 資源），會造成誤判。
// 真正的封鎖是被重導到 /sorry/ 路徑，以 URL 判定最可靠。
const BLOCK_RE = /unusual traffic|異常流量|我不是機器人|驗證您是人類|系統偵測到.*異常/i;
const BLOCK_URL_RE = /\/sorry\/|\/recaptcha\/api2\/|captcha_redirect/i;

async function scrapeOne(page, url, timeoutMs) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
  // 等「整趟行程」出現＝多城市總價已渲染。
  // 不能等「正在載入結果」消失——那是常駐文字，會白等到逾時。
  await page.waitForFunction(
    () => document.body.innerText.includes('整趟行程'),
    { timeout: timeoutMs });

  const body = await page.innerText('body');
  if (BLOCK_URL_RE.test(page.url()) || BLOCK_RE.test(body)) {
    return { status: 'blocked' };
  }

  const options = await page.$$eval('li', (els) => els
    .map((e) => e.innerText)
    .filter((t) => t.includes('整趟行程'))
    .map((t) => {
      const m = t.match(/\$([0-9,]+)/);
      if (!m) return null;
      const air = t.match(/\n([^\n]*航空[^\n]*)\n/);
      return {
        price: parseInt(m[1].replace(/,/g, ''), 10),
        airline: air ? air[1].trim() : '',
        business: /商務艙/.test(t),
      };
    })
    .filter(Boolean));

  // 只取經濟艙——四段票的甜蜜點在經濟艙，商務艙在多城市會跳艙翻倍
  const economy = options.filter((o) => !o.business);
  const pool = economy.length ? economy : options;
  if (!pool.length) return { status: 'empty' };
  const best = pool.reduce((a, b) => (b.price < a.price ? b : a));
  return {
    status: 'ok',
    price: best.price,
    airline: best.airline,
    option_count: pool.length,
  };
}

(async () => {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const cfg = JSON.parse(input || '{}');
  const urls = cfg.urls || [];
  const minDelay = cfg.min_delay_ms != null ? cfg.min_delay_ms : 5000;
  const maxDelay = cfg.max_delay_ms != null ? cfg.max_delay_ms : 11000;
  const maxRetries = cfg.max_retries != null ? cfg.max_retries : 1;
  const sessionLimit = cfg.session_limit != null ? cfg.session_limit : 50;
  const timeoutMs = cfg.timeout_ms != null ? cfg.timeout_ms : 25000;

  const exe = findChromium();
  if (!exe) {
    process.stdout.write(JSON.stringify({
      type: 'summary', blocked: false,
      error: '找不到 chromium：請執行 npx playwright install chromium',
    }) + '\n');
    return;
  }

  const browser = await chromium.launch({
    headless: true,
    executablePath: exe,
    // 拿掉 navigator.webdriver 等最明顯的自動化特徵
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const ctx = await browser.newContext({
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();

  const results = [];
  let blocked = false;
  let softBlocked = false;
  let consecutiveFail = 0;
  const t00 = Date.now();
  const todo = urls.slice(0, sessionLimit);

  // 軟封鎖：Google 不一定回 captcha，更常見的是讓請求靜默逾時。
  // 2026-09-22 實測：前 20 筆正常，第 21 筆起連續 16 次逾時，但因為沒有
  // captcha 字樣，原本的 BLOCK_RE 完全沒觸發，白打了 16 次——繼續打只會
  // 加深封鎖。連續失敗達此門檻即視同被擋並中止。
  const SOFT_BLOCK_THRESHOLD = 3;

  for (let i = 0; i < todo.length; i++) {
    const item = todo[i];
    let out = null;
    // 已經連續失敗過就別再重試：被擋的情況下重試必然也失敗，只是把
    // 軟封鎖的偵測時間從 30 秒拖到 60 秒（2026-09-23 實測）。
    const retriesNow = consecutiveFail > 0 ? 0 : maxRetries;
    for (let attempt = 0; attempt <= retriesNow; attempt++) {
      const t0 = Date.now();
      try {
        out = await scrapeOne(page, item.url, timeoutMs);
      } catch (e) {
        out = { status: /Timeout/i.test(e.message) ? 'timeout' : 'error',
                error: e.message.split('\n')[0] };
      }
      out.secs = Number(((Date.now() - t0) / 1000).toFixed(1));
      if (out.status === 'ok' || out.status === 'blocked') break;
      if (attempt < maxRetries) await sleep(rnd(minDelay, maxDelay));
    }
    const row = Object.assign({ type: 'result', id: item.id }, out);
    results.push(row);
    process.stdout.write(JSON.stringify(row) + '\n');   // 逐筆即時落地
    process.stderr.write(
      `[${i + 1}/${todo.length}] ${item.id} ${out.status} ${out.secs}s ` +
      `${out.price ? out.price.toLocaleString() : ''}\n`);

    // 一旦真的被擋就立刻停止：繼續打只會加深封鎖
    if (out.status === 'blocked') { blocked = true; break; }

    if (out.status === 'ok') {
      consecutiveFail = 0;
    } else {
      consecutiveFail++;
      if (consecutiveFail >= SOFT_BLOCK_THRESHOLD) {
        blocked = true;
        softBlocked = true;
        process.stderr.write(
          `連續 ${consecutiveFail} 次失敗，研判為軟封鎖，中止掃描。` +
          `請隔一段時間再試，或加大 --min-delay／--max-delay。\n`);
        break;
      }
    }
    if (i < todo.length - 1) await sleep(rnd(minDelay, maxDelay));
  }

  process.stdout.write(JSON.stringify({
    type: 'summary',
    blocked,
    soft_blocked: softBlocked,
    stats: {
      requested: urls.length,
      attempted: results.length,
      ok: results.filter((r) => r.status === 'ok').length,
      elapsed_sec: Number(((Date.now() - t00) / 1000).toFixed(1)),
    },
  }) + '\n');
  await browser.close();
})();
