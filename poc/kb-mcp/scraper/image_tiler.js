/**
 * 長圖切片的像素處理（010 T035、research R5）——只在本機處理圖片檔，**不連任何網站、不連網**。
 *
 * 為什麼用瀏覽器 canvas：Python 標準庫無法解碼 PNG，而 plan 規定不新增 Python 套件；Playwright 與
 * findChromium() 本來就是既有依賴（T034 決定）。圖片以 data: URL 載入，canvas 不會被 tainted。
 *
 * 輸入（stdin 一個 JSON）：
 *   { mode: "bands", path, scale_width?, tolerance?, min_band?, blank_fraction? }
 *       → 偵測近乎同色的橫向空白帶（整列 ≥ blank_fraction 的像素與該列主色相近），輸出一行
 *         {type:"bands", width, height, bands:[[起列, 止列(不含)], ...]}（座標為 scale_width 縮放後的）
 *   { mode: "slice", path, scale_width?, cuts:[[top,bottom], ...], out_dir }
 *       → 依切點（座標為 scale_width 縮放後的）輸出 PNG 切片到 out_dir/tile_NN.png，每片一行
 *         {type:"tile", index, path, width, height}
 * 結尾一定輸出 {type:"summary", ok, error?}。找不到瀏覽器 → ok=false, error="no_browser"。
 * scale_width 省略或等於原寬 → 不縮放（切片逐像素原樣）。
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { findChromium, readStdin, emit } = require('./investanchors_session');

function mimeOf(buf) {
  if (buf.length > 8 && buf[0] === 0x89 && buf[1] === 0x50) return 'image/png';
  if (buf.length > 3 && buf[0] === 0xff && buf[1] === 0xd8) return 'image/jpeg';
  if (buf.length > 12 && buf.slice(0, 4).toString() === 'RIFF' && buf.slice(8, 12).toString() === 'WEBP') return 'image/webp';
  if (buf.length > 4 && buf.slice(0, 3).toString() === 'GIF') return 'image/gif';
  return 'application/octet-stream';
}

// 以下函式在瀏覽器頁面內執行（page.evaluate），不能引用外層變數。
async function pageLoad(args) {
  const img = new Image();
  await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('image_decode_failed')); img.src = args.dataUrl; });
  const W = img.naturalWidth, H = img.naturalHeight;
  const sw = args.scaleWidth && args.scaleWidth !== W ? args.scaleWidth : W;
  const scale = sw / W;
  const sh = Math.round(H * scale);
  const c = document.createElement('canvas');
  c.width = sw; c.height = sh;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, 0, 0, sw, sh);
  window.__img = img; window.__canvas = c; window.__ctx = ctx; window.__scale = scale;
  return { width: sw, height: sh, origWidth: W, origHeight: H };
}

function pageBands(args) {
  const c = window.__canvas, ctx = window.__ctx;
  const w = c.width, h = c.height;
  const data = ctx.getImageData(0, 0, w, h).data;
  const tol = args.tolerance, need = Math.ceil(w * args.blankFraction);
  const hist = new Uint32Array(4096);
  const blank = new Uint8Array(h);
  for (let y = 0; y < h; y++) {
    const base = y * w * 4;
    hist.fill(0);
    let bestKey = 0, bestCnt = 0, rep = 0;
    for (let x = 0; x < w; x++) {
      const i = base + x * 4;
      const k = ((data[i] >> 4) << 8) | ((data[i + 1] >> 4) << 4) | (data[i + 2] >> 4);
      const n = ++hist[k];
      if (n > bestCnt) { bestCnt = n; bestKey = k; rep = i; }
    }
    if (bestCnt < need * 0.5) continue; // 主色桶連一半都不到，肯定不是空白列
    const r0 = data[rep], g0 = data[rep + 1], b0 = data[rep + 2];
    let near = 0;
    for (let x = 0; x < w; x++) {
      const i = base + x * 4;
      if (Math.abs(data[i] - r0) <= tol && Math.abs(data[i + 1] - g0) <= tol && Math.abs(data[i + 2] - b0) <= tol) near++;
    }
    if (near >= need) blank[y] = 1;
  }
  const bands = [];
  let s = -1;
  for (let y = 0; y <= h; y++) {
    if (y < h && blank[y]) { if (s < 0) s = y; }
    else if (s >= 0) { if (y - s >= args.minBand) bands.push([s, y]); s = -1; }
  }
  return bands;
}

function pageSlice(args) {
  const img = window.__img, scale = window.__scale, w = window.__canvas.width;
  const out = [];
  for (const [top, bottom] of args.cuts) {
    const h = bottom - top;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, 0, top / scale, img.naturalWidth, h / scale, 0, 0, w, h);
    out.push({ width: w, height: h, b64: c.toDataURL('image/png').split(',')[1] });
  }
  return out;
}

async function main() {
  const cfg = JSON.parse(await readStdin());
  const exe = findChromium();
  if (!exe) { emit({ type: 'summary', ok: false, error: 'no_browser' }); return; }
  let browser;
  try {
    const buf = fs.readFileSync(cfg.path);
    const dataUrl = 'data:' + mimeOf(buf) + ';base64,' + buf.toString('base64');
    browser = await chromium.launch({ executablePath: exe, headless: true });
    const page = await (await browser.newContext()).newPage();
    await page.goto('about:blank');
    const info = await page.evaluate(pageLoad, { dataUrl, scaleWidth: cfg.scale_width || 0 });
    if (cfg.mode === 'bands') {
      const bands = await page.evaluate(pageBands, {
        tolerance: cfg.tolerance == null ? 10 : cfg.tolerance,
        minBand: cfg.min_band || 4,
        blankFraction: cfg.blank_fraction || 0.99,
      });
      emit({ type: 'bands', width: info.width, height: info.height, bands });
    } else if (cfg.mode === 'slice') {
      fs.mkdirSync(cfg.out_dir, { recursive: true });
      const tiles = await page.evaluate(pageSlice, { cuts: cfg.cuts });
      tiles.forEach((t, i) => {
        const p = path.join(cfg.out_dir, 'tile_' + String(i + 1).padStart(2, '0') + '.png');
        fs.writeFileSync(p, Buffer.from(t.b64, 'base64'));
        emit({ type: 'tile', index: i + 1, path: p, width: t.width, height: t.height });
      });
    } else {
      throw new Error('unknown_mode');
    }
    emit({ type: 'summary', ok: true });
  } catch (e) {
    emit({ type: 'summary', ok: false, error: String(e && e.message || e).slice(0, 200) });
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

main();
