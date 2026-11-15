/**
 * 定錨產業筆記（investanchors.com）瀏覽器抓取。目前只實作 probe（探查）模式；
 * 日後的 list／articles 模式在同一支檔案擴充（specs/010 contracts/cli.md §4）。
 *
 * 用法（由 article_probe.py 呼叫，不手動執行）：
 *   echo '{"mode":"probe","email":...,"password":...}' | node investanchors_scraper.js
 * 帳密只經 stdin 傳入，不出現在 argv／環境變數／stderr／stdout。
 *
 * 輸出為 JSON Lines：{"type":"fact","step":...,"data":{...}} 逐步事實，
 * 最後一行 {"type":"summary",...}。進度訊息走 stderr，且只有步驟代號。
 *
 * probe 的硬性規約（specs/010 research R0）：每次執行登入 1 次、清單頁最多 3 頁、
 * 文章最多開 2 篇、全程單一 context；**結束必走伺服器端登出並驗證**（context.close()
 * 只清本機 cookie，不算登出）；找不到登出機制就停止並回報；只輸出結構事實——
 * 不輸出文章標題、全文、cookie、帳密、CSRF token。
 *
 * 登出的穩健性：登出連結常藏在使用者下拉選單且可能是 data-method="delete"，
 * 所以依序嘗試 (a)展開選單再點 (b)頁面內 el.click() (c)以同源請求送出對應方法
 * (d)GET，**每一步之後都驗證**，第一個驗證成功即停。任何異常路徑與收到
 * SIGINT／SIGTERM 時，只要目前頁面找得到登出機制就先登出再結束。
 */
const { chromium } = require('playwright');
const fsp = require('fs');
const path = require('path');
const os = require('os');
const { sameSite } = require('./site_util');

const HARD = { logins: 1, listPages: 3, articles: 2, navigations: 12 };
const ENTRY_PATH = '/user/vip_contents/investanchors_index';
const LOGOUT_RE_SRC = '登出|log\\s*-?out|sign\\s*-?out';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rnd = (a, b) => a + Math.random() * (b - a);
const step = (name) => process.stderr.write('[probe] ' + name + '\n');
const emit = (obj) => process.stdout.write(JSON.stringify(obj) + '\n');
const fact = (name, data) => emit({ type: 'fact', step: name, data });

function findChromium() {
  const systemChrome =
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  if (fsp.existsSync(systemChrome)) return systemChrome;
  const base = path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright');
  if (!fsp.existsSync(base)) return null;
  const full = [];
  for (const dir of fsp.readdirSync(base)) {
    if (!/^chromium-/.test(dir)) continue;
    for (const sub of [
      'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
      'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
    ]) {
      const p = path.join(base, dir, sub);
      if (fsp.existsSync(p)) full.push(p);
    }
  }
  full.sort().reverse();
  return full[0] || null;
}

const BLOCK_URL_RE = /\/sorry\/|captcha|\/blocked|\/forbidden/i;
const PW_SEL = 'input[type="password"]';
const EMAIL_SEL =
  'input[type="email"], input[name*="email" i], input[name*="mail" i], input[id*="email" i]';
const TEXT_INPUT_SEL =
  'input:not([type]), input[type="text"], input[type="email"], input[type="tel"], input[type="number"]';

function readStdin() {
  return new Promise((resolve, reject) => {
    let buf = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { buf += c; });
    process.stdin.on('end', () => resolve(buf));
    process.stdin.on('error', reject);
  });
}

async function probe(cfg) {
  const baseUrl = String(cfg.base_url || 'https://investanchors.com').replace(/\/+$/, '');
  const baseHost = new URL(baseUrl).host;
  const timeoutMs = cfg.timeout_ms || 30000;
  const delayRange = cfg.delay_ms || [30000, 90000];
  const lim = {
    listPages: Math.min(cfg.max_list_pages || HARD.listPages, HARD.listPages),
    articles: Math.min(cfg.max_articles == null ? HARD.articles : cfg.max_articles,
                       HARD.articles),
  };
  const counters = { logins: 0, list_pages: 0, articles_opened: 0, navigations: 0 };
  const st = {
    blocked: false, logged_in: false, logout_found: false, logged_out: false,
    logout_verified: false, stage_error: null, login_at: null, logout_at: null,
  };
  let timeouts = 0;
  let aborting = false;
  let summaryEmitted = false;
  let logoutPromise = null;
  let loginSubmitted = false;

  const exe = findChromium();
  if (!exe) {
    emit({ type: 'summary', counters, ...st, stage_error: 'no_browser' });
    return;
  }
  const browser = await chromium.launch({
    executablePath: exe, headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
    // Playwright 預設收到訊號就先關瀏覽器，導致無法登出；改由下方自己的處理器先登出再結束。
    handleSIGINT: false, handleSIGTERM: false, handleSIGHUP: false,
  });
  const context = await browser.newContext({
    locale: 'zh-TW', timezoneId: 'Asia/Taipei',
    viewport: { width: 1366, height: 900 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(timeoutMs);

  function emitSummary() {
    if (summaryEmitted) return;
    summaryEmitted = true;
    emit({ type: 'summary', counters, ...st });
  }

  // 每次（前進用的）導覽都經過這裡：計數、上限、禮貌間隔、被擋偵測。
  async function go(url, kind) {
    if (aborting) throw new Error('aborting');
    if (counters.navigations >= HARD.navigations) {
      st.stage_error = 'navigation_cap';
      throw new Error('navigation_cap');
    }
    if (counters.navigations > 0) await sleep(rnd(delayRange[0], delayRange[1]));
    if (aborting) throw new Error('aborting');
    counters.navigations += 1;
    let resp = null;
    try {
      resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
      timeouts = 0;
    } catch (e) {
      timeouts += 1;
      if (timeouts >= 2) { st.blocked = true; st.stage_error = 'blocked_timeouts'; }
      throw e;
    }
    const u = new URL(page.url());
    const status = resp ? resp.status() : 0;
    if (status === 403 || status === 429 || BLOCK_URL_RE.test(u.pathname) ||
        !sameSite(u.host, baseHost)) {
      st.blocked = true;
      st.stage_error = 'blocked_unexpected_page';
      throw new Error('blocked');
    }
    return { status, kind };
  }

  // 找登出機制並在元素上做標記（data-probe-logout=序號），供後續各種嘗試定位。
  // 只回方法名（data-method），不回 token。
  async function findLogout() {
    return page.evaluate((reSrc) => {
      const re = new RegExp(reSrc, 'i');
      const hrefRe = /log-?out|sign[_-]?out/i;
      for (const old of document.querySelectorAll('[data-probe-logout]')) {
        old.removeAttribute('data-probe-logout');
      }
      const out = [];
      for (const el of document.querySelectorAll('a,button,input[type=submit],form')) {
        const text = ((el.innerText || el.value || '') + '').trim().slice(0, 20);
        const href = el.getAttribute('href') || el.getAttribute('action') || '';
        if (re.test(text) || hrefRe.test(href)) {
          if (out.length < 5) el.setAttribute('data-probe-logout', String(out.length));
          out.push({
            tag: el.tagName.toLowerCase(), text,
            href_path: href.split('?')[0].slice(0, 100),
            method: (el.getAttribute('method') || '').toUpperCase(),
            data_method: (el.getAttribute('data-method') || '').toLowerCase().slice(0, 10),
            visible: !!(el.offsetWidth || el.offsetHeight),
          });
        }
      }
      return out.slice(0, 5);
    }, LOGOUT_RE_SRC);
  }

  async function verifyLoggedOut() {
    try {
      counters.logout_navigations = (counters.logout_navigations || 0) + 1;
      await page.goto(baseUrl + ENTRY_PATH, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
      const formVisible = await page.locator(PW_SEL + ':visible').first().isVisible().catch(() => false);
      const still = (await findLogout()).length > 0;
      return formVisible && !still;
    } catch (e) {
      return false;
    }
  }

  const logoutAttempts = {
    // (a) 展開使用者選單（或已可見）再點
    async menu_click() {
      const visibleLoc = () => page.locator('[data-probe-logout]:visible').first();
      if ((await visibleLoc().count()) === 0) {
        const toggles = page.locator(
          '[data-toggle="dropdown"], [data-bs-toggle="dropdown"], .dropdown-toggle, ' +
          '[aria-haspopup="true"], [aria-haspopup="menu"]');
        const n = Math.min(await toggles.count(), 3);
        for (let i = 0; i < n && (await visibleLoc().count()) === 0; i += 1) {
          await toggles.nth(i).click({ timeout: 3000 }).catch(() => {});
          await page.waitForTimeout(400);
        }
      }
      if ((await visibleLoc().count()) === 0) return false;
      await visibleLoc().click({ timeout: 8000 });
      return true;
    },
    // (b) 頁面內 el.click()：對隱藏元素也有效，且會經過網站自己的 JS（data-method）
    async js_click() {
      return page.evaluate(() => {
        const els = Array.from(document.querySelectorAll('[data-probe-logout]'));
        const el = els.find((e) => e.tagName !== 'FORM') || els[0];
        if (!el) return false;
        if (el.tagName === 'FORM') {
          if (el.requestSubmit) el.requestSubmit(); else el.submit();
        } else {
          el.click();
        }
        return true;
      });
    },
    // (c) 讀 data-method 與 CSRF token，以同源請求送出對應方法（token 不離開頁面）
    async fetch() {
      return page.evaluate(async () => {
        const el = document.querySelector('[data-probe-logout]');
        if (!el) return false;
        const href = el.getAttribute('href') || el.getAttribute('action') || '';
        if (!href) return false;
        const url = new URL(href, location.href);
        if (url.host !== location.host) return false;
        const dm = (el.getAttribute('data-method') || el.getAttribute('method') || 'get').toLowerCase();
        const meta = document.querySelector('meta[name="csrf-token"]');
        const token = meta ? meta.content : '';
        const base = { credentials: 'same-origin' };
        if (dm === 'get') {
          await fetch(url.toString(), { ...base, method: 'GET', headers: { 'X-CSRF-Token': token } });
          return true;
        }
        const body = new URLSearchParams({ _method: dm, authenticity_token: token });
        await fetch(url.toString(), {
          ...base, method: 'POST', body,
          headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/x-www-form-urlencoded' },
        });
        if (dm === 'delete' || dm === 'put' || dm === 'patch') {
          await fetch(url.toString(), {
            ...base, method: dm.toUpperCase(), headers: { 'X-CSRF-Token': token },
          }).catch(() => {});
        }
        return true;
      });
    },
    // (d) 最後才是 GET
    async get() {
      const mech = await page.evaluate(() => {
        const el = document.querySelector('[data-probe-logout]');
        return el ? (el.getAttribute('href') || '') : '';
      });
      if (!mech) return false;
      const target = new URL(mech, baseUrl);
      if (!sameSite(target.host, baseHost)) return false;
      await page.goto(target.toString(), { waitUntil: 'domcontentloaded', timeout: timeoutMs });
      return true;
    },
  };

  async function runLogoutFlow() {
    const attempts = [];
    let verified = false;
    for (const method of ['menu_click', 'js_click', 'fetch', 'get']) {
      let mech = [];
      try { mech = await findLogout(); } catch (e) { mech = []; }
      if (!mech.length) {
        if (await verifyLoggedOut()) { verified = true; attempts.push({ method, acted: false, verified: true }); break; }
        attempts.push({ method, acted: false, verified: false });
        await sleep(rnd(1500, 3000));
        continue;
      }
      let acted = false;
      try { acted = !!(await logoutAttempts[method]()); } catch (e) { acted = false; }
      await page.waitForTimeout(1200);
      const ok = acted ? await verifyLoggedOut() : false;
      attempts.push({ method, acted, verified: ok });
      if (ok) { verified = true; break; }
      await sleep(rnd(1500, 3000));
    }
    st.logged_out = verified;
    st.logout_verified = verified;
    st.logout_at = new Date().toISOString();
    fact('logout', { verified, attempts });
    return verified;
  }

  const ensureLogout = () => {
    if (!logoutPromise) logoutPromise = runLogoutFlow();
    return logoutPromise;
  };

  async function logoutIfPossible() {
    let mech = [];
    try { mech = await findLogout(); } catch (e) { mech = []; }
    if (st.logged_in || loginSubmitted || mech.length) await ensureLogout();
  }

  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, async () => {
      if (aborting) return;
      aborting = true;
      st.stage_error = st.stage_error || 'signal_' + sig;
      try { await logoutIfPossible(); } catch (e) { /* ignore */ }
      emitSummary();
      try { await browser.close(); } catch (e) { /* ignore */ }
      process.exit(sig === 'SIGINT' ? 130 : (sig === 'SIGHUP' ? 129 : 143));
    });
  }

  async function extractList() {
    return page.evaluate(() => {
      const items = [];
      const seen = new Set();
      for (const a of document.querySelectorAll('a[href*="vip_contents"]')) {
        const m = (a.getAttribute('href') || '').match(/vip_contents\/(\d+)/);
        if (!m) continue;
        const id = Number(m[1]);
        if (seen.has(id)) continue;
        seen.add(id);
        const row = a.closest('tr, li, .row, article') || a.parentElement || a;
        const rowText = row.innerText || '';
        const full = rowText.match(/(\d{4})\s*[-\/.年]\s*(\d{1,2})\s*[-\/.月]\s*(\d{1,2})/);
        const md = full ? null : rowText.match(/(\d{1,2})\s*[-\/.月]\s*(\d{1,2})/);
        const pad = (n) => String(n).padStart(2, '0');
        const weight = parseInt(getComputedStyle(a).fontWeight, 10) || 400;
        items.push({
          article_id: id,
          date: full ? full[1] + '-' + pad(full[2]) + '-' + pad(full[3]) : null,
          md: md ? pad(md[1]) + '-' + pad(md[2]) : null,
          is_announcement: (a.innerText || '').trim().startsWith('【公告】'),
          read_state: weight >= 600 ? 'bold' : 'normal',
        });
      }
      return items;
    });
  }

  async function listFacts() {
    return page.evaluate(() => {
      const q = (s) => Array.from(document.querySelectorAll(s));
      const nextRel = q('a[rel="next"]')[0];
      const nextText = q('a').find((a) => /下一頁|next|›|»/i.test((a.innerText || '').trim()));
      const next = nextRel || nextText || null;
      const pageLinks = q('a[href*="page="], a[href*="p="]');
      const keys = new Set();
      for (const a of pageLinks) {
        try {
          for (const k of new URL(a.href, location.href).searchParams.keys()) keys.add(k);
        } catch (e) { /* ignore */ }
      }
      const tabs = q('a[href*="lv="]').map((a) => {
        let lv = null;
        try { lv = new URL(a.href, location.href).searchParams.get('lv'); } catch (e) { /* ignore */ }
        return { text: (a.innerText || '').trim().slice(0, 10), lv };
      }).slice(0, 12);
      const loadMore = q('button, a').some((b) => /載入更多|load more|顯示更多/i.test(b.innerText || ''));
      return {
        has_rel_next: !!nextRel,
        has_next_link: !!next,
        next_href: next ? (next.getAttribute('href') || '') : null,
        page_link_count: pageLinks.length,
        page_query_keys: Array.from(keys),
        load_more_button: loadMore,
        tabs,
      };
    });
  }

  async function articleFacts() {
    // 分段捲動以觸發延遲載入（不增加導覽次數）
    await page.evaluate(async () => {
      const h = document.body.scrollHeight;
      for (let y = 0; y < h; y += 600) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 250));
      }
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(800);
    return page.evaluate(async (sameHost) => {
      const ps = Array.from(document.querySelectorAll('p'));
      const scores = new Map();
      for (const p of ps) {
        const par = p.parentElement;
        if (!par) continue;
        scores.set(par, (scores.get(par) || 0) + (p.innerText || '').length);
      }
      let best = null;
      let bestLen = -1;
      for (const [el, len] of scores) if (len > bestLen) { best = el; bestLen = len; }
      const root = document.querySelector('#inves_content') || best;
      const desc = (el) => el ? {
        tag: el.tagName.toLowerCase(),
        id: (el.id || '').slice(0, 30),
        classes: Array.from(el.classList).slice(0, 3).map((c) => c.slice(0, 30)),
      } : null;
      const chain = [];
      for (let e = root, i = 0; e && i < 3; e = e.parentElement, i += 1) chain.push(desc(e));
      const shape = (u) => {
        try {
          const x = new URL(u, location.href);
          return {
            same_host: x.host === sameHost,
            host: x.host,
            path_shape: x.pathname.replace(/[0-9a-f]{6,}|\d+/gi, '#').slice(0, 80),
            ext: (x.pathname.match(/\.([a-z0-9]{2,4})$/i) || [null, ''])[1].toLowerCase(),
          };
        } catch (e) { return { same_host: false, host: '', path_shape: '', ext: '' }; }
      };
      const allImgs = Array.from(document.querySelectorAll('img'));
      const inRoot = root ? Array.from(root.querySelectorAll('img')) : [];
      const imgs = inRoot.slice(0, 20).map((im) => {
        const src = im.currentSrc || im.src || '';
        const w = im.naturalWidth || 0;
        const h = im.naturalHeight || 0;
        const r = im.getBoundingClientRect();
        return {
          w, h, aspect: h ? Math.round((w / h) * 100) / 100 : 0,
          rendered_w: Math.round(r.width), rendered_h: Math.round(r.height),
          complete: !!im.complete,
          has_alt: !!(im.getAttribute('alt') || '').trim(),
          src_is_data_uri: src.startsWith('data:'),
          lazy_attr: !!(im.getAttribute('data-src') || im.getAttribute('data-original') ||
                        im.getAttribute('data-lazy-src')),
          loading_attr: (im.getAttribute('loading') || '').slice(0, 10),
          has_srcset: !!im.getAttribute('srcset'),
          in_table: !!im.closest('table'),
          in_link: !!im.closest('a'),
          parent_tag: im.parentElement ? im.parentElement.tagName.toLowerCase() : '',
          ...shape(src),
        };
      });
      let bgCount = 0;
      if (root) {
        const all = root.querySelectorAll('*');
        for (let i = 0; i < Math.min(all.length, 2000); i += 1) {
          if (getComputedStyle(all[i]).backgroundImage !== 'none') bgCount += 1;
        }
      }
      const tables = root ? Array.from(root.querySelectorAll('table')).slice(0, 10).map((t) => {
        const rows = Array.from(t.querySelectorAll('tr'));
        return {
          rows: rows.length,
          max_cols: rows.reduce((m, r) => Math.max(m, r.children.length), 0),
          has_img: !!t.querySelector('img'),
          has_thead: !!t.querySelector('thead'),
          text_len: (t.innerText || '').length,
        };
      }) : [];
      const checks = [];
      for (const im of inRoot.filter((x) => !(x.currentSrc || x.src || '').startsWith('data:')).slice(0, 2)) {
        const src = im.currentSrc || im.src;
        try {
          const r = await fetch(src, { credentials: 'omit' });
          checks.push({
            status: r.status,
            content_type: (r.headers.get('content-type') || '').slice(0, 40),
            same_host: shape(src).same_host,
          });
          try { if (r.body) r.body.cancel(); } catch (e) { /* ignore */ }
        } catch (e) {
          checks.push({ error: 'fetch_failed', same_host: shape(src).same_host });
        }
      }
      const titleCands = [];
      for (const sel of ['h1', 'h2', 'h3', '[class*="title" i]']) {
        const el = document.querySelector(sel);
        if (el) titleCands.push({ sel, ...desc(el), text_len: (el.innerText || '').length });
      }
      const dateCands = Array.from(document.querySelectorAll(
        'time, [class*="date" i], [id*="date" i], [class*="time" i]')).slice(0, 3).map((el) => ({
        ...desc(el),
        text_shape: (el.innerText || '').trim().replace(/\d/g, '#').slice(0, 30),
      }));
      return {
        container_chain: chain,
        body_text_len: bestLen < 0 ? 0 : bestLen,
        paragraph_count: ps.length,
        h1_count: document.querySelectorAll('h1').length,
        title_candidates: titleCands,
        date_candidates: dateCands,
        time_element: !!document.querySelector('time'),
        comments_section: !!document.querySelector('[id*="comment" i], [class*="comment" i]'),
        content_images: imgs,
        content_image_count: inRoot.length,
        outside_image_count: allImgs.length - inRoot.length,
        content_background_image_elements: bgCount,
        content_tables: tables,
        content_iframes: root ? root.querySelectorAll('iframe').length : 0,
        content_canvas: root ? root.querySelectorAll('canvas').length : 0,
        content_svg: root ? root.querySelectorAll('svg').length : 0,
        image_download_check_without_cookies: checks,
      };
    }, baseHost);
  }

  // 登入：以第一個「可見」的密碼欄位找到所屬 form，其餘欄位與送出鈕都限定在該 form 內；
  // 看起來像註冊表單（文字欄位 >2、或密碼欄位 >1）或找不到所屬 form → 不送出。
  async function submitLogin() {
    const pwFirst = page.locator(PW_SEL + ':visible').first();
    if ((await pwFirst.count()) === 0) return { ok: false, reason: 'no_login_form' };
    const formHandle = await pwFirst.evaluateHandle((el) => el.closest('form'));
    const formEl = formHandle.asElement();
    if (!formEl) return { ok: false, reason: 'ambiguous_login_form' };
    const info = await formEl.evaluate((f, sel) => ({
      pw: f.querySelectorAll('input[type="password"]').length,
      text: f.querySelectorAll(sel).length,
    }), TEXT_INPUT_SEL);
    if (info.pw !== 1 || info.text > 2) return { ok: false, reason: 'ambiguous_login_form' };
    await formEl.evaluate((f) => f.setAttribute('data-probe-login', '1'));
    const F = page.locator('form[data-probe-login="1"]');
    const email = F.locator(EMAIL_SEL).first();
    const emailField = (await email.count()) > 0 ? email : F.locator(TEXT_INPUT_SEL).first();
    if ((await emailField.count()) === 0) return { ok: false, reason: 'ambiguous_login_form' };
    const pw = F.locator(PW_SEL).first();
    const remember = F.locator('input[type="checkbox"]').first();
    const hasRemember = (await remember.count()) > 0;
    let rememberDefault = null;
    if (hasRemember) {
      rememberDefault = await remember.isChecked().catch(() => null);
      if (rememberDefault) await remember.uncheck().catch(() => {});
    }
    await emailField.fill(cfg.email);
    await pw.fill(cfg.password);
    let submit = F.locator('button[type="submit"], input[type="submit"]').first();
    if ((await submit.count()) === 0) submit = F.locator('button').first();
    counters.navigations += 1;
    loginSubmitted = true;
    await Promise.all([
      page.waitForLoadState('domcontentloaded').catch(() => {}),
      submit.click(),
    ]);
    await page.waitForTimeout(1500);
    const stillForm = await page.locator(PW_SEL + ':visible').first().isVisible().catch(() => false);
    if (!stillForm) {
      return { ok: true, remember_checkbox: hasRemember, remember_default_checked: rememberDefault };
    }
    const body = (await page.innerText('body').catch(() => '')) || '';
    let reason = 'unknown';
    if (/停用|鎖定|凍結|裝置.*(上限|超過)|已超過/.test(body)) reason = 'account_disabled';
    else if (/錯誤|不正確|invalid|incorrect|failed/i.test(body)) reason = 'bad_credentials';
    return { ok: false, reason, remember_checkbox: hasRemember,
             remember_default_checked: rememberDefault };
  }

  try {
    step('login');
    await go(baseUrl + ENTRY_PATH, 'entry');
    counters.logins += 1;
    if (counters.logins > HARD.logins) throw new Error('login_cap');
    const login = await submitLogin();
    if (aborting) throw new Error('aborting');
    fact('login', {
      ok: login.ok, reason: login.reason || null,
      final_path: new URL(page.url()).pathname,
      scheme: new URL(page.url()).protocol,
      remember_checkbox: !!login.remember_checkbox,
      remember_default_checked: login.remember_default_checked,
    });
    if (!login.ok) {
      st.stage_error = login.reason === 'ambiguous_login_form'
        ? 'ambiguous_login_form' : 'login_failed:' + login.reason;
      throw new Error('login');
    }
    st.logged_in = true;
    st.login_at = new Date().toISOString();

    step('list-1');
    await go(baseUrl + ENTRY_PATH, 'list');
    counters.list_pages += 1;
    const mechanisms = await findLogout();
    fact('logout_mechanism', { found: mechanisms.length > 0, candidates: mechanisms });
    st.logout_found = mechanisms.length > 0;
    if (!st.logout_found) { st.stage_error = 'no_logout_mechanism'; throw new Error('no_logout'); }

    const page1 = await extractList();
    const lf = await listFacts();
    let paging = lf.has_next_link ? 'link_pagination'
      : (lf.load_more_button ? 'load_more_button' : 'unknown');
    if (paging === 'unknown') {
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(2000);
      const after = await extractList();
      paging = after.length > page1.length ? 'infinite_scroll' : 'single_page';
    }
    fact('list_page_1', { items: page1, items_per_page: page1.length, paging_type: paging, ...lf });

    let page2Items = [];
    if (paging === 'link_pagination' && counters.list_pages < lim.listPages && lf.next_href) {
      step('list-2');
      await go(new URL(lf.next_href, baseUrl).toString(), 'list');
      counters.list_pages += 1;
      const page2 = await extractList();
      page2Items = page2;
      const ids1 = new Set(page1.map((i) => i.article_id));
      fact('list_page_2', {
        items: page2, items_per_page: page2.length,
        overlap_with_page1: page2.filter((i) => ids1.has(i.article_id)).length,
      });
    }

    const dupIds = new Set(page1.filter((i) => page2Items.some((j) => j.article_id === i.article_id))
      .map((i) => i.article_id));
    // 排除公告與跨頁重複項（疑似置頂的舊文），避免挑到不具代表性的文章
    const nonAnn = page1.filter((i) => !i.is_announcement && !dupIds.has(i.article_id));
    const explicit = (cfg.target_article_ids || []).map(String)
      .filter((x) => /^\d{1,20}$/.test(x)).slice(0, lim.articles);
    let targetIds = explicit.slice();
    if (explicit.length === 0) {
      targetIds = nonAnn.slice(0, lim.articles).map((i) => String(i.article_id));
    } else if (targetIds.length < lim.articles) {
      const free = nonAnn.filter((i) => !targetIds.includes(String(i.article_id)));
      const ctrl = free.find((i) => i.read_state === 'bold') || free[0];
      if (ctrl) targetIds.push(String(ctrl.article_id));
    }
    const known = page1.concat(page2Items);
    const before = {};
    for (const id of targetIds) {
      const it = known.find((i) => String(i.article_id) === id);
      before[id] = it ? it.read_state : null;
    }
    for (const id of targetIds) {
      step('article');
      await go(baseUrl + '/user/vip_contents/' + id, 'article');
      counters.articles_opened += 1;
      fact('article', {
        article_id: Number(id), explicitly_requested: explicit.includes(id),
        was_in_list_pages_1_2: before[id] !== null, ...(await articleFacts()),
      });
    }

    if (targetIds.length && counters.list_pages < lim.listPages) {
      step('list-recheck');
      await go(baseUrl + ENTRY_PATH, 'list');
      counters.list_pages += 1;
      const re = await extractList();
      const changes = targetIds.map((id) => {
        const now = re.find((i) => String(i.article_id) === id);
        return { article_id: Number(id), before: before[id], after: now ? now.read_state : null };
      });
      fact('read_state', {
        changed: changes.some((c) => c.before && c.after && c.after !== c.before),
        was_unread_before: changes.some((c) => c.before === 'bold'),
        comparisons: changes,
      });
    }
  } catch (e) {
    if (!st.stage_error) st.stage_error = 'exception:' + (e && e.name ? e.name : 'Error');
  } finally {
    step('logout');
    try { await logoutIfPossible(); } catch (e) { /* ignore */ }
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    emitSummary();
  }
}

(async () => {
  let cfg;
  try {
    cfg = JSON.parse(await readStdin());
  } catch (e) {
    emit({ type: 'summary', counters: {}, stage_error: 'bad_stdin' });
    process.exit(2);
  }
  if (cfg.mode !== 'probe') {
    emit({ type: 'summary', counters: {}, stage_error: 'unsupported_mode' });
    process.exit(2);
  }
  try {
    await probe(cfg);
  } catch (e) {
    emit({ type: 'summary', counters: {}, stage_error: 'fatal:' + (e && e.name ? e.name : 'Error') });
    process.exit(1);
  }
})();
