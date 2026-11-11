/* content.js — 扫描、队列引擎、拟人节奏、自动翻页、持久化日志 */
(function () {
  'use strict';

  const t = (k, v) => window.WBS_I18N.t(k, v);
  const Panel = window.WBS_Panel;

  const DEFAULT_SETTINGS = {
    delayMin: 2.5,
    delayMax: 5,
    batchSize: 10,
    cooldownEnabled: true,
    cooldownMin: 20,
    cooldownMax: 45,
    maxRetries: 3,
    maxPages: 20,
    rangeStart: 0,   // 订阅范围起始序号（1 基）；0 = 从第 1 个开始
    rangeEnd: 0      // 订阅范围结束序号；0 = 到最后一个
  };

  const JOB_KEY = 'wbs_job';
  const SETTINGS_KEY = 'wbs_settings';
  const LOG_KEY = 'wbs_log';
  const LOG_MAX = 300;

  const state = {
    running: false,
    paused: false,
    cancelled: false,
    mode: 'subscribe',
    auto: false,            // 自动翻页模式
    queue: [],
    total: 0,
    done: 0,
    ok: 0,
    fail: 0,
    pagesDone: 0,
    pageOk: 0,
    pageFail: 0,
    lastFailed: [],
    settings: { ...DEFAULT_SETTINGS },
    auth: { loggedIn: false, sessionId: null },
    logCache: []
  };

  /* ---------- 工具 ---------- */

  const rand = (min, max) => min + Math.random() * (max - min);

  function sleep(ms) {
    // 每 200ms 检查一次暂停/取消标志
    return new Promise((resolve) => {
      let waited = 0;
      const tick = () => {
        if (state.cancelled) return resolve(false);
        if (state.paused) return setTimeout(tick, 300);
        waited += 200;
        if (waited >= ms) return resolve(true);
        setTimeout(tick, 200);
      };
      tick();
    });
  }

  // 批次冷却：每秒把剩余秒数刷到状态栏；暂停时计时冻结，取消则立即返回 false
  async function cooldown(totalSec) {
    let remain = Math.max(1, Math.round(totalSec));
    while (remain > 0) {
      Panel.setStatus('cooldownMsg', { s: remain }, true);
      const cont = await sleep(1000);
      if (!cont) return false;
      remain--;
    }
    return true;
  }

  function getAppId() {
    const m = location.search.match(/[?&]appid=(\d+)/);
    return m ? m[1] : null;
  }

  function getPageNo() {
    const m = location.search.match(/[?&]p=(\d+)/);
    return m ? parseInt(m[1], 10) : 1;
  }

  function buildPageUrl(p) {
    const url = new URL(location.href);
    url.searchParams.set('p', String(p));
    return url.toString();
  }

  // 页面签名：同一游戏、同一筛选/排序才允许跨页续跑，防止串页
  function pageSignature() {
    const u = new URL(location.href);
    u.searchParams.delete('p');
    return u.pathname + u.search;
  }

  /* ---------- 总页数探测（读分页 UI 的数字按钮，取最大值） ---------- */

  // 返回最后一页页码；0 = 未发现分页（单页或尚未渲染）
  function getLastPage() {
    // 覆盖 Steam 创意工坊新旧版分页 DOM：div[role=button]、a、button、
    // span[role=button]、以及带 page/pager/pagn 类名或 aria-label 的容器内元素
    const selectors = [
      'div[role="button"]',
      'span[role="button"]',
      'a[href*="?p="]',
      'a',
      'button',
      '[class*="page" i]',
      '[class*="pager" i]',
      '[class*="pagn" i]',
      '[aria-label*="page" i]',
      '[aria-label*="pager" i]'
    ];
    const candidates = new Set();
    for (const sel of selectors) {
      try {
        document.querySelectorAll(sel).forEach((e) => candidates.add(e));
      } catch { /* 选择器在某些浏览器可能不支持，跳过 */ }
    }

    const groups = new Map(); // 父元素 -> {count, max}
    for (const e of candidates) {
      // 只统计可见元素，排除 display:none 的占位
      if (e.offsetParent === null) continue;
      const txt = (e.textContent || '').trim().replace(/[,\s]/g, '');
      if (!/^\d{1,7}$/.test(txt)) continue;
      const n = parseInt(txt, 10);
      if (n < 1) continue;
      const p = e.parentElement;
      if (!p) continue;
      const g = groups.get(p) || { count: 0, max: 0 };
      g.count++;
      g.max = Math.max(g.max, n);
      groups.set(p, g);
    }
    let last = 0;
    for (const g of groups.values()) {
      // 至少 2 个数字按钮才认为是分页区，排除单个数字（如物品数量）
      if (g.count >= 2 && g.max > last) last = g.max;
    }
    return last;
  }

  /* ---------- 登录态（后台读 HttpOnly Cookie，DOM 兜底） ---------- */

  function fallbackSessionId() {
    const m = document.cookie.match(/(?:^|;\s*)sessionid=([^;]+)/);
    return m ? m[1] : null;
  }

  function domLoggedInHint() {
    if (document.querySelector('#account_pulldown')) return true;
    for (const a of document.querySelectorAll('a[href*="login"]')) {
      if (/log\s*in|登录/i.test(a.textContent || '')) return false;
    }
    return null;
  }

  async function refreshAuth() {
    try {
      const r = await chrome.runtime.sendMessage({ type: 'wbs:auth' });
      if (r && r.loggedIn !== null && r.loggedIn !== undefined) {
        state.auth = {
          loggedIn: !!r.loggedIn,
          sessionId: r.sessionId || fallbackSessionId()
        };
        return state.auth;
      }
    } catch (e) { /* 后台不可用时走 DOM 兜底 */ }
    state.auth = {
      loggedIn: domLoggedInHint() === true,
      sessionId: fallbackSessionId()
    };
    return state.auth;
  }

  const authReady = () => state.auth.loggedIn && !!state.auth.sessionId;

  /* ---------- 持久化日志 ---------- */

  async function loadLog() {
    const data = await chrome.storage.local.get(LOG_KEY);
    state.logCache = Array.isArray(data[LOG_KEY]) ? data[LOG_KEY] : [];
    Panel.restoreLogs(state.logCache);
  }

  let logWriteChain = Promise.resolve();
  function persistLog(entry) {
    state.logCache.push(entry);
    if (state.logCache.length > LOG_MAX) {
      state.logCache = state.logCache.slice(-LOG_MAX);
    }
    // 串行写入，避免并发覆盖
    logWriteChain = logWriteChain.then(() =>
      chrome.storage.local.set({ [LOG_KEY]: state.logCache }).catch(() => {})
    );
    return logWriteChain;
  }

  function log(msg, cls) {
    const entry = { ts: Date.now(), msg, cls: cls || '' };
    Panel.log(entry.msg, entry.cls, entry.ts);
    persistLog(entry);
  }

  function exportLog() {
    const fmt = (ts) => {
      const d = new Date(ts);
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    };
    const lines = state.logCache.map((e) => `[${fmt(e.ts)}]${e.cls ? ' [' + e.cls.toUpperCase() + ']' : ''} ${e.msg}`);
    const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `workshop-batch-subscribe-log-${Date.now()}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  /* ---------- 页面扫描 ---------- */

  function scanItems() {
    const seen = new Set();
    const items = [];
    for (const a of document.querySelectorAll('a[href*="sharedfiles/filedetails/?id="]')) {
      const m = a.href.match(/filedetails\/\?id=(\d+)/);
      if (!m) continue;
      const id = m[1];
      if (seen.has(id)) continue;
      seen.add(id);
      const img = a.querySelector('img');
      const title = (img && img.alt) || a.textContent.trim() || id;
      items.push({ id, title, tries: 0 });
    }
    return items;
  }

  /* ---------- 订阅请求 ---------- */

  async function callSteam(id) {
    const endpoint = state.mode === 'unsubscribe'
      ? 'https://steamcommunity.com/sharedfiles/unsubscribe'
      : 'https://steamcommunity.com/sharedfiles/subscribe';
    const resp = await fetch(endpoint, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
      body: new URLSearchParams({
        id,
        appid: getAppId(),
        sessionid: state.auth.sessionId || ''
      }).toString()
    });
    if (resp.redirected && /login/i.test(resp.url)) {
      const e = new Error('auth');
      e.auth = true;
      throw e;
    }
    if (resp.status === 429 || resp.status >= 500) {
      const e = new Error('http ' + resp.status);
      e.status = resp.status;
      e.retryAfter = parseInt(resp.headers.get('Retry-After') || '0', 10);
      throw e;
    }
    if (!resp.ok) return false;

    // 校验业务结果：Steam 返回 JSON { success: 1 }
    let j = null;
    try { j = JSON.parse(await resp.text()); } catch { /* 非 JSON */ }
    if (!j) {
      // 返回 HTML：多半被踢到登录页
      const e = new Error('auth');
      e.auth = true;
      throw e;
    }
    return String(j.success) === '1';
  }

  async function callWithRetries(item) {
    const max = state.settings.maxRetries;
    let authRefreshed = false;
    for (let attempt = 1; attempt <= max + 1; attempt++) {
      try {
        return await callSteam(item.id);
      } catch (e) {
        if (e.auth) {
          // 先尝试刷新一次会话（Cookie 可能轮换）
          if (!authRefreshed) {
            authRefreshed = true;
            await refreshAuth();
            if (authReady()) continue;
          }
          log(t('notLoggedIn'), 'fail');
          Panel.setStatus('statusBackoff', null, true);
          state.cancelled = true;
          return false;
        }
        if (attempt > max) return false;
        let waitSec = e.retryAfter > 0 ? Math.min(e.retryAfter, 300) : Math.pow(2, attempt) * 5;
        Panel.setStatus('statusBackoff', null, true);
        log(t('waitingRetry', { s: waitSec, n: attempt }), 'info');
        const cont = await sleep(waitSec * 1000);
        if (!cont) return false;
      }
    }
    return false;
  }

  /* ---------- 队列引擎 ---------- */

  function updateBadge() {
    const remaining = state.total - state.done;
    chrome.runtime.sendMessage({
      type: 'wbs:badge',
      text: state.running && remaining > 0 ? String(remaining) : '',
      color: state.mode === 'unsubscribe' ? '#c25050' : '#5c7e10'
    }).catch(() => {});
  }

  function refreshPanel() {
    Panel.setProgress(state.done, state.total);
    updateBadge();
  }

  async function runQueue() {
    state.running = true;
    state.cancelled = false;
    state.paused = false;
    Panel.setRunning(true);
    Panel.setPauseLabel(false);
    Panel.setMode(state.mode);
    Panel.setStatus('statusRunning');
    refreshPanel();

    const s = state.settings;
    if (!s.cooldownEnabled) log(t('cooldownDisabled'), 'info');
    let sinceBatch = 0;

    for (let i = 0; i < state.queue.length; i++) {
      if (state.cancelled) break;
      const item = state.queue[i];

      // 拟人间隔
      const cont = await sleep(rand(s.delayMin, s.delayMax) * 1000);
      if (!cont) break;

      // 逐项进度，如 3/29
      Panel.setStatus('progressItem', { i: i + 1, total: state.queue.length });

      const okItem = await callWithRetries(item);
      if (state.cancelled) break;

      state.done++;
      const prefix = `[${i + 1}/${state.queue.length}]`;
      if (okItem) {
        state.ok++;
        state.pageOk++;
        log(`${prefix} [${t('itemOk')}] ${item.title}`, 'ok');
      } else {
        state.fail++;
        state.pageFail++;
        state.lastFailed.push(item);
        log(`${prefix} [${t('itemFail')}] ${item.title}`, 'fail');
      }
      refreshPanel();

      // 批次冷却（可在设置中关闭；倒计时每秒刷新到状态栏）
      sinceBatch++;
      if (s.cooldownEnabled && sinceBatch >= s.batchSize && i < state.queue.length - 1 && !state.cancelled) {
        sinceBatch = 0;
        const cd = Math.round(rand(s.cooldownMin, s.cooldownMax));
        log(t('cooldownMsg', { s: cd }), 'info');
        const c = await cooldown(cd);
        if (!c) break;
        Panel.setStatus('statusRunning');
      }
    }

    // 每页完成提示（本页成功/失败计数）
    if (!state.cancelled) {
      log(t('pageDone', { p: getPageNo(), ok: state.pageOk, fail: state.pageFail }), 'info');
    }

    // 自动翻页：本页完成后跳下一页；末页/上限两种终止条件
    // 注意：last===0 时（分页 UI 探测失败）不直接停止，而是尝试翻到下一页，
    // 由 resumeJobIfAny 中的重复页守卫（首项 ID 相同）判定是否真的到末页
    if (!state.cancelled && state.auto) {
      const cur = getPageNo();
      let last = getLastPage();
      if (last === 0) {
        // 分页可能尚未渲染，等一下再确认一次
        await sleep(1500);
        last = getLastPage();
      }
      if (last > 0 && cur >= last) {
        log(t('lastPage'), 'info');
        finish('statusDone');
        return;
      }
      if (state.pagesDone + 1 >= s.maxPages) {
        log(t('maxPagesHit', { n: s.maxPages }), 'info');
        finish('statusDone');
        return;
      }
      await saveJob();
      await logWriteChain; // 确保日志落盘后再跳页
      const next = getPageNo() + 1;
      if (last === 0) {
        log(t('nextPageProbe', { p: next }), 'info');
      } else {
        log(t('nextPage', { p: next }), 'info');
      }
      await logWriteChain;
      location.href = buildPageUrl(next);
      return; // 页面即将卸载
    }

    finish(state.cancelled ? 'statusCancelled' : 'statusDone');
  }

  function finish(statusKey) {
    state.running = false;
    Panel.setRunning(false);
    Panel.setStatus(statusKey);
    log(t('doneSummary', { ok: state.ok, fail: state.fail }), state.fail > 0 ? 'info' : 'ok');
    Panel.setProgress(state.done, state.total || 1);
    updateBadge();
    clearJob();
  }

  /* ---------- 跨页任务持久化 ---------- */

  async function saveJob() {
    const job = {
      active: true,
      mode: state.mode,
      auto: state.auto,
      ok: state.ok,
      fail: state.fail,
      pagesDone: state.pagesDone + 1,
      failed: state.lastFailed,
      firstId: state.queue.length ? state.queue[0].id : null,
      sig: pageSignature(),
      ts: Date.now()
    };
    await chrome.storage.local.set({ [JOB_KEY]: job });
  }

  async function clearJob() {
    await chrome.storage.local.remove(JOB_KEY);
  }

  async function resumeJobIfAny() {
    const data = await chrome.storage.local.get(JOB_KEY);
    const job = data[JOB_KEY];
    if (!job || !job.active) return;

    // 防串页：签名不一致（换了游戏/筛选）则丢弃旧任务
    if (job.sig && job.sig !== pageSignature()) {
      await clearJob();
      return;
    }

    // 已知总页数且已越界：直接终止（无需登录）
    const cur = getPageNo();
    const last = getLastPage();
    if (job.auto && last > 0 && cur > last) {
      log(t('lastPage'), 'info');
      log(t('doneSummary', { ok: job.ok || 0, fail: job.fail || 0 }), (job.fail || 0) > 0 ? 'info' : 'ok');
      Panel.setStatus('statusDone');
      await clearJob();
      return;
    }

    // 空页 = 自动翻页的终止条件（无需登录即可判定，先判终止再验登录）
    const items = scanItems();
    // 重复页守卫：Steam 对越界页码会钳制回末页，首项与上页相同即说明未再前进
    if (items.length > 0 && job.auto && job.firstId && items[0].id === job.firstId) {
      log(t('lastPage'), 'info');
      log(t('doneSummary', { ok: job.ok || 0, fail: job.fail || 0 }), (job.fail || 0) > 0 ? 'info' : 'ok');
      Panel.setStatus('statusDone');
      await clearJob();
      return;
    }
    if (items.length === 0) {
      if (job.auto) {
        log(t('lastPage'), 'info');
        log(t('doneSummary', { ok: job.ok || 0, fail: job.fail || 0 }), (job.fail || 0) > 0 ? 'info' : 'ok');
        Panel.setStatus('statusDone');
      } else {
        log(t('noItems'), 'fail');
      }
      await clearJob();
      return;
    }

    // 登录失效：保留任务，等用户重新登录后可继续
    await refreshAuth();
    if (!authReady()) {
      log(t('notLoggedIn'), 'fail');
      Panel.setStatus('statusIdle');
      return;
    }

    log(t('nextPage', { p: getPageNo() }), 'info');
    state.mode = job.mode;
    state.auto = !!job.auto;
    state.ok = job.ok || 0;
    state.fail = job.fail || 0;
    state.pagesDone = job.pagesDone || 0;
    state.lastFailed = Array.isArray(job.failed) ? job.failed : [];
    startQueue(items);
  }

  /* ---------- 启动入口 ---------- */

  function startQueue(items) {
    state.queue = items;
    state.total = items.length;
    state.done = 0;
    state.pageOk = 0;
    state.pageFail = 0;
    runQueue();
  }

  // 应用用户设定的订阅序号范围（1 基，闭区间；0/空 = 端点默认值）
  function applyRange(items) {
    const r = Panel.getRange();
    state.settings.rangeStart = r.start;
    state.settings.rangeEnd = r.end;
    chrome.storage.local.set({ [SETTINGS_KEY]: state.settings }).catch(() => {});

    let a = r.start > 0 ? r.start : 1;
    let b = r.end > 0 ? r.end : items.length;
    a = Math.max(1, Math.min(a, items.length));
    b = Math.max(1, Math.min(b, items.length));
    if (a > b) { const tmp = a; a = b; b = tmp; log(t('rangeAutoFixed'), 'info'); }
    Panel.setRange(a, b === items.length ? 0 : b);
    const picked = items.slice(a - 1, b);
    log(t('rangeApply', { a, b, n: picked.length }), 'info');
    return picked;
  }

  async function begin(mode, auto, itemsOverride) {
    if (state.running) return;
    await refreshAuth();
    if (!authReady()) {
      log(t('notLoggedIn'), 'fail');
      Panel.setStatus('statusIdle');
      return;
    }
    const scanned = itemsOverride || scanItems();
    if (scanned.length === 0) {
      log(t('noItems'), 'fail');
      return;
    }
    // 重试失败项时使用原始列表；正常启动应用用户设定的序号范围
    const items = itemsOverride ? scanned : applyRange(scanned);
    state.mode = mode;
    state.auto = auto;
    state.ok = 0;
    state.fail = 0;
    state.pagesDone = 0;
    state.lastFailed = [];
    if (auto) log(t('pageStart', { p: getPageNo() }), 'info');
    startQueue(items);
  }

  /* ---------- 设置 ---------- */

  async function loadSettings() {
    const data = await chrome.storage.local.get(SETTINGS_KEY);
    state.settings = { ...DEFAULT_SETTINGS, ...(data[SETTINGS_KEY] || {}) };
    Panel.renderSettings(state.settings, async (next) => {
      // 基本校正
      next.cooldownEnabled = !!next.cooldownEnabled;
      if (next.delayMax < next.delayMin) next.delayMax = next.delayMin;
      if (next.cooldownMax < next.cooldownMin) next.cooldownMax = next.cooldownMin;
      next.maxPages = Math.max(1, Math.min(100, Math.round(next.maxPages) || DEFAULT_SETTINGS.maxPages));
      // 订阅范围来自面板上的独立输入框，而不是设置表单
      const r = Panel.getRange();
      next.rangeStart = Math.max(0, r.start);
      next.rangeEnd = Math.max(0, r.end);
      state.settings = { ...state.settings, ...next };
      await chrome.storage.local.set({ [SETTINGS_KEY]: state.settings });
      Panel.setRange(state.settings.rangeStart, state.settings.rangeEnd);
    });
    Panel.setRange(state.settings.rangeStart, state.settings.rangeEnd);
  }

  /* ---------- 面板刷新 / 更新检查 ---------- */

  async function doRefresh() {
    // 重新读取设置（含冷却等改动）、重新检测登录、重新扫描当前页
    await loadSettings();
    await refreshAuth();
    const n = scanItems().length;
    Panel.setFound(n);
    Panel.setStatus(state.running ? 'statusRunning' : 'statusIdle');
    log(t('refreshed', { n }), 'info');
  }

  async function checkUpdateNow(force) {
    try {
      const info = await chrome.runtime.sendMessage({ type: 'wbs:checkUpdate', force: !!force });
      if (!info) return;
      if (info.hasUpdate && info.url) {
        Panel.showUpdate(info.latest, info.url);
        log(t('updateAvailable', { v: info.latest }) + ' ' + info.url, 'info');
      } else if (force) {
        log(info.error ? t('updateCheckFailed') + info.error : t('upToDate', { v: info.current }), info.error ? 'fail' : 'ok');
      }
    } catch (e) {
      if (force) log(t('updateCheckFailed') + e, 'fail');
    }
  }

  /* ---------- 初始化 ---------- */

  function init() {
    Panel.mount(chrome.runtime.getManifest().version);
    Panel.setFound(scanItems().length);

    Panel.on('refresh', doRefresh);
    Panel.on('checkUpdate', () => checkUpdateNow(true));
    Panel.on('subscribePage', () => begin('subscribe', false));
    Panel.on('subscribePages', () => begin('subscribe', true));
    Panel.on('unsubscribePage', () => {
      if (!window.confirm(t('unsubConfirm'))) return;
      begin('unsubscribe', false);
    });
    Panel.on('pause', () => {
      if (!state.running) return;
      state.paused = !state.paused;
      Panel.setPauseLabel(state.paused);
      Panel.setStatus(state.paused ? 'statusPaused' : 'statusRunning');
    });
    Panel.on('cancel', () => {
      state.cancelled = true;
      state.paused = false;
    });
    Panel.on('retryFailed', () => {
      // 精准重试失败项（无失败项时忽略）
      if (state.lastFailed.length === 0) {
        log(t('noFailed'), 'info');
        return;
      }
      const items = state.lastFailed.slice();
      begin(state.mode, false, items);
    });
    Panel.on('exportLog', exportLog);

    // 初始化：恢复日志 → 检测登录态并明示 → 加载设置 → 恢复跨页任务 → 后台静默检查更新
    loadLog()
      .then(refreshAuth)
      .then(() => log(t(authReady() ? 'authOk' : 'notLoggedIn'), authReady() ? 'info' : 'fail'))
      .then(loadSettings)
      .then(resumeJobIfAny)
      .then(() => checkUpdateNow(false));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
