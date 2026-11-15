/**
 * 定錨產業筆記 scraper 的共用 session 模組（010 T011）。
 *
 * 由探查模式（investanchors_scraper.js probe）已驗證過的寫法抽出，**行為不變**；後續 `import`
 * 模式（T013／T014）重用同一份，不得另寫第二套登入／登出：
 *   - 全新 context、不持久化 profile、Playwright 內建訊號處理關閉（它預設先關瀏覽器，會讓登出失敗）；
 *   - go()：導覽計數、上限、禮貌間隔、被擋偵測（403／429／導向非本站／連續 2 次逾時）；
 *   - submitLogin()：第一個可見密碼欄位所屬 form，像註冊表單即 ambiguous_login_form，不送出；
 *   - runLogoutFlow()：四段式（展開選單點／頁面內 click／帶 CSRF 的同源請求／GET）每步驗證；
 *   - ensureLogout()／logoutIfPossible()：任何異常與 SIGINT／SIGTERM／SIGHUP 都先登出再結束。
 * 帳密只經 stdin（cfg）傳入，不出現在 argv／環境變數／stderr／stdout。
 */
const { chromium } = require('playwright');
const fsp = require('fs');
const path = require('path');
const os = require('os');
const { sameSite } = require('./site_util');

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

/**
 * 啟動瀏覽器 session。opts：
 *   navigationCap（前進用導覽的總上限，預設 12）、counters（額外的計數欄位，會出現在 summary）。
 * 找不到瀏覽器時輸出 summary（stage_error=no_browser）並回傳 null。
 */
async function launchSession(cfg, opts) {
  opts = opts || {};
  const navigationCap = opts.navigationCap || 12;
  const baseUrl = String(cfg.base_url || 'https://investanchors.com').replace(/\/+$/, '');
  const baseHost = new URL(baseUrl).host;
  const timeoutMs = cfg.timeout_ms || 30000;
  const delayRange = cfg.delay_ms || [30000, 90000];
  const counters = Object.assign({ logins: 0, navigations: 0 }, opts.counters || {});
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
    return null;
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
    if (counters.navigations >= navigationCap) {
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

  return {
    cfg, baseUrl, baseHost, timeoutMs, delayRange, counters, st, browser, context, page,
    emitSummary, go, findLogout, verifyLoggedOut, runLogoutFlow, ensureLogout, logoutIfPossible,
    submitLogin, isAborting: () => aborting,
  };
}

module.exports = {
  launchSession, ENTRY_PATH, sleep, rnd, step, emit, fact, readStdin, findChromium,
  PW_SEL, EMAIL_SEL, TEXT_INPUT_SEL, BLOCK_URL_RE,
};
