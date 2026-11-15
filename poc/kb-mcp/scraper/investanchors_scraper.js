/**
 * 定錨產業筆記（investanchors.com）瀏覽器抓取。目前實作 probe（探查）模式；
 * 日後的 import 模式在同一支檔案擴充（specs/010 contracts/cli.md §4）。
 * 登入／登出／被擋偵測／訊號處理一律來自共用模組 investanchors_session.js（T011），不在此重寫。
 *
 * 用法（由 article_probe.py 呼叫，不手動執行）：
 *   echo '{"mode":"probe","email":...,"password":...}' | node investanchors_scraper.js
 * 帳密只經 stdin 傳入，不出現在 argv／環境變數／stderr／stdout。
 *
 * 輸出為 JSON Lines：{"type":"fact","step":...,"data":{...}} 逐步事實，
 * 最後一行 {"type":"summary",...}。進度訊息走 stderr，且只有步驟代號。
 *
 * probe 的硬性規約（specs/010 research R0）：每次執行登入 1 次、清單頁最多 3 頁、
 * 文章最多開 2 篇、全程單一 context；**結束必走伺服器端登出並驗證**；找不到登出機制就停止並回報；
 * 只輸出結構事實——不輸出文章標題、全文、cookie、帳密、CSRF token。
 */
const {
  launchSession, ENTRY_PATH, step, emit, fact, readStdin,
} = require('./investanchors_session');

const HARD = { logins: 1, listPages: 3, articles: 2, navigations: 12 };

async function probe(cfg) {
  const lim = {
    listPages: Math.min(cfg.max_list_pages || HARD.listPages, HARD.listPages),
    articles: Math.min(cfg.max_articles == null ? HARD.articles : cfg.max_articles,
                       HARD.articles),
  };
  const sess = await launchSession(cfg, {
    navigationCap: HARD.navigations,
    counters: { list_pages: 0, articles_opened: 0 },
  });
  if (!sess) return;
  const {
    baseUrl, baseHost, counters, st, browser, context, page, emitSummary, go, findLogout,
    logoutIfPossible, submitLogin,
  } = sess;

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

  try {
    step('login');
    await go(baseUrl + ENTRY_PATH, 'entry');
    counters.logins += 1;
    if (counters.logins > HARD.logins) throw new Error('login_cap');
    const login = await submitLogin();
    if (sess.isAborting()) throw new Error('aborting');
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
