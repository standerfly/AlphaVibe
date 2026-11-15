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
 * 不輸出文章標題、全文、cookie、帳密。
 */
const { chromium } = require('playwright');
const fsp = require('fs');
const path = require('path');
const os = require('os');

const HARD = { logins: 1, listPages: 3, articles: 2, navigations: 12 };
const ENTRY_PATH = '/user/vip_contents/investanchors_index';

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

  const exe = findChromium();
  if (!exe) {
    emit({ type: 'summary', counters, ...st, stage_error: 'no_browser' });
    return;
  }
  const browser = await chromium.launch({
    executablePath: exe, headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const context = await browser.newContext({
    locale: 'zh-TW', timezoneId: 'Asia/Taipei',
    viewport: { width: 1366, height: 900 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(timeoutMs);

  // 每次導覽都經過這裡：計數、上限、禮貌間隔、被擋偵測。
  async function go(url, kind) {
    if (counters.navigations >= HARD.navigations) {
      st.stage_error = 'navigation_cap';
      throw new Error('navigation_cap');
    }
    if (counters.navigations > 0) await sleep(rnd(delayRange[0], delayRange[1]));
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
        u.host !== baseHost) {
      st.blocked = true;
      st.stage_error = 'blocked_unexpected_page';
      throw new Error('blocked');
    }
    return { status, kind };
  }

  async function findLogout() {
    return page.evaluate(() => {
      const re = /登出|log\s*-?out|sign\s*-?out/i;
      const hrefRe = /log-?out|sign[_-]?out/i;
      const out = [];
      for (const el of document.querySelectorAll('a,button,input[type=submit],form')) {
        const text = ((el.innerText || el.value || '') + '').trim().slice(0, 20);
        const href = el.getAttribute('href') || el.getAttribute('action') || '';
        if (re.test(text) || hrefRe.test(href)) {
          out.push({
            tag: el.tagName.toLowerCase(), text,
            href_path: href.split('?')[0].slice(0, 100),
            method: (el.getAttribute('method') || '').toUpperCase(),
            visible: !!(el.offsetWidth || el.offsetHeight),
          });
        }
      }
      return out.slice(0, 5);
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
    return page.evaluate((sameHost) => {
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
      const desc = (el) => el ? {
        tag: el.tagName.toLowerCase(),
        id: (el.id || '').slice(0, 30),
        classes: Array.from(el.classList).slice(0, 3).map((c) => c.slice(0, 30)),
      } : null;
      const chain = [];
      for (let e = best, i = 0; e && i < 3; e = e.parentElement, i += 1) chain.push(desc(e));
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
      const imgs = Array.from(document.querySelectorAll('img')).slice(0, 20).map((im) => {
        const s = shape(im.currentSrc || im.src || im.getAttribute('data-src') || '');
        const w = im.naturalWidth || 0;
        const h = im.naturalHeight || 0;
        return {
          in_container: !!(best && best.contains(im)),
          w, h, aspect: h ? Math.round((w / h) * 100) / 100 : 0,
          has_alt: !!(im.getAttribute('alt') || '').trim(),
          lazy_attr: !!im.getAttribute('data-src'),
          ...s,
        };
      });
      const dateEl = document.querySelector('time');
      return {
        container_chain: chain,
        body_text_len: bestLen < 0 ? 0 : bestLen,
        paragraph_count: ps.length,
        h1_count: document.querySelectorAll('h1').length,
        html_table_count: document.querySelectorAll('table').length,
        time_element: !!dateEl,
        comments_section: !!document.querySelector('[id*="comment" i], [class*="comment" i]'),
        images: imgs,
        total_image_count: document.querySelectorAll('img').length,
      };
    }, baseHost);
  }

  async function submitLogin() {
    const pw = page.locator(PW_SEL).first();
    const email = page.locator(EMAIL_SEL).first();
    if (!(await pw.isVisible().catch(() => false))) return { ok: false, reason: 'no_login_form' };
    const remember = page.locator('input[type="checkbox"]').first();
    const hasRemember = (await remember.count()) > 0;
    let rememberDefault = null;
    if (hasRemember) {
      rememberDefault = await remember.isChecked().catch(() => null);
      if (rememberDefault) await remember.uncheck().catch(() => {});
    }
    await email.fill(cfg.email);
    await pw.fill(cfg.password);
    const submit = page.locator('button[type="submit"], input[type="submit"]').first();
    const hasSubmit = (await submit.count()) > 0;
    counters.navigations += 1;
    await Promise.all([
      page.waitForLoadState('domcontentloaded').catch(() => {}),
      hasSubmit ? submit.click() : page.locator('button:has-text("登入")').first().click(),
    ]);
    await page.waitForTimeout(1500);
    const stillForm = await page.locator(PW_SEL).first().isVisible().catch(() => false);
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

  async function doLogout(mechanisms) {
    const m = (mechanisms || []).find((x) => x.visible) || (mechanisms || [])[0];
    if (!m) return false;
    counters.navigations += 1;
    let done = false;
    const loc = m.href_path
      ? page.locator('a[href^="' + m.href_path + '"], form[action^="' + m.href_path + '"] [type=submit], button').filter({ hasText: /登出|log\s*-?out|sign\s*-?out/i }).first()
      : page.locator('button, input[type=submit]').filter({ hasText: /登出|log\s*-?out|sign\s*-?out/i }).first();
    try {
      await Promise.all([
        page.waitForLoadState('domcontentloaded').catch(() => {}),
        loc.click({ timeout: 8000 }),
      ]);
      done = true;
    } catch (e) {
      if (m.tag === 'a' && m.href_path) {
        try { await page.goto(new URL(m.href_path, baseUrl).toString(),
                              { waitUntil: 'domcontentloaded', timeout: timeoutMs });
              done = true; } catch (e2) { /* fall through */ }
      }
    }
    await page.waitForTimeout(1000);
    return done;
  }

  async function verifyLoggedOut() {
    try {
      counters.navigations += 1;
      await page.goto(baseUrl + ENTRY_PATH, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
      const formVisible = await page.locator(PW_SEL).first().isVisible().catch(() => false);
      const still = (await findLogout()).length > 0;
      return formVisible && !still;
    } catch (e) {
      return false;
    }
  }

  let mechanisms = null;
  try {
    step('login');
    await go(baseUrl + ENTRY_PATH, 'entry');
    counters.logins += 1;
    if (counters.logins > HARD.logins) throw new Error('login_cap');
    const login = await submitLogin();
    fact('login', {
      ok: login.ok, reason: login.reason || null,
      final_path: new URL(page.url()).pathname,
      scheme: new URL(page.url()).protocol,
      remember_checkbox: !!login.remember_checkbox,
      remember_default_checked: login.remember_default_checked,
    });
    if (!login.ok) { st.stage_error = 'login_failed:' + login.reason; throw new Error('login'); }
    st.logged_in = true;
    st.login_at = new Date().toISOString();

    step('list-1');
    await go(baseUrl + ENTRY_PATH, 'list');
    counters.list_pages += 1;
    mechanisms = await findLogout();
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

    let allItems = page1.slice();
    if (paging === 'link_pagination' && counters.list_pages < lim.listPages && lf.next_href) {
      step('list-2');
      await go(new URL(lf.next_href, baseUrl).toString(), 'list');
      counters.list_pages += 1;
      const page2 = await extractList();
      const ids1 = new Set(page1.map((i) => i.article_id));
      fact('list_page_2', {
        items: page2, items_per_page: page2.length,
        overlap_with_page1: page2.filter((i) => ids1.has(i.article_id)).length,
      });
      allItems = allItems.concat(page2);
    }

    const targets = page1.filter((i) => !i.is_announcement).slice(0, lim.articles);
    const before = {};
    for (const t of targets) before[t.article_id] = t.read_state;
    for (const t of targets) {
      step('article');
      await go(baseUrl + '/user/vip_contents/' + t.article_id, 'article');
      counters.articles_opened += 1;
      fact('article', { article_id: t.article_id, ...(await articleFacts()) });
    }

    if (targets.length && counters.list_pages < lim.listPages) {
      step('list-recheck');
      await go(baseUrl + ENTRY_PATH, 'list');
      counters.list_pages += 1;
      const re = await extractList();
      const changes = targets.map((t) => {
        const now = re.find((i) => i.article_id === t.article_id);
        return { article_id: t.article_id, before: before[t.article_id],
                 after: now ? now.read_state : null };
      });
      fact('read_state', {
        changed: changes.some((c) => c.after && c.after !== c.before),
        comparisons: changes,
      });
      mechanisms = await findLogout().catch(() => mechanisms);
    }
  } catch (e) {
    if (!st.stage_error) st.stage_error = 'exception:' + (e && e.name ? e.name : 'Error');
  } finally {
    if (st.logged_in) {
      step('logout');
      try {
        if (!mechanisms || !mechanisms.length) mechanisms = await findLogout().catch(() => []);
        const clicked = await doLogout(mechanisms);
        st.logged_out = clicked;
        st.logout_at = new Date().toISOString();
        st.logout_verified = clicked ? await verifyLoggedOut() : false;
      } catch (e) {
        st.logged_out = false;
      }
      fact('logout', { clicked: st.logged_out, verified: st.logout_verified });
    }
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    emit({ type: 'summary', counters, ...st });
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
