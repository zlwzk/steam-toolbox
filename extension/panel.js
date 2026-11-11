/* panel.js — 注入式悬浮面板 UI */
(function () {
  'use strict';

  const t = (k, v) => window.WBS_I18N.t(k, v);
  let root = null;
  const handlers = {};
  const els = {};

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function btn(id, label, cls) {
    const b = el('button', 'wbs-btn' + (cls ? ' ' + cls : ''), label);
    b.id = 'wbs-' + id;
    b.addEventListener('click', () => handlers[id] && handlers[id]());
    return b;
  }

  function numInput(id, value, min, max, step) {
    const i = document.createElement('input');
    i.type = 'number';
    i.id = 'wbs-set-' + id;
    i.value = value;
    i.min = min; i.max = max;
    if (step) i.step = step;
    return i;
  }

  function checkInput(id, value) {
    const i = document.createElement('input');
    i.type = 'checkbox';
    i.id = 'wbs-set-' + id;
    i.checked = !!value;
    return i;
  }

  function build(version) {
    if (root) return root;

    root = el('div');
    root.id = 'wbs-panel';

    // header
    const header = el('div', 'wbs-header');
    const title = el('span', 'wbs-title', t('panelTitle'));
    els.ver = el('span', 'wbs-ver', version ? 'v' + version : '');
    els.mode = el('span', 'wbs-badge-mode', t('modeSubscribe'));
    const refreshBtn = el('button', 'wbs-icon-btn', '↻');
    refreshBtn.title = t('refresh');
    refreshBtn.addEventListener('click', () => handlers['refresh'] && handlers['refresh']());
    const updateBtn = el('button', 'wbs-icon-btn', '⇪');
    updateBtn.title = t('checkUpdate');
    updateBtn.addEventListener('click', () => handlers['checkUpdate'] && handlers['checkUpdate']());
    const gear = el('button', 'wbs-icon-btn', '⚙');
    gear.title = t('settings');
    gear.addEventListener('click', () => els.settings.classList.toggle('wbs-open'));
    const logExp = el('button', 'wbs-icon-btn', '⇩');
    logExp.title = t('exportLog');
    logExp.addEventListener('click', () => handlers['exportLog'] && handlers['exportLog']());
    const logTgl = el('button', 'wbs-icon-btn', '≡');
    logTgl.title = t('log');
    logTgl.addEventListener('click', () => els.log.classList.toggle('wbs-open'));
    const collapse = el('button', 'wbs-icon-btn', '—');
    collapse.title = t('collapse');
    collapse.addEventListener('click', () => {
      const collapsed = root.classList.toggle('wbs-collapsed');
      collapse.textContent = collapsed ? '□' : '—';
    });
    header.append(title, els.ver, els.mode, refreshBtn, updateBtn, logExp, logTgl, gear, collapse);

    // 更新提示横幅（默认隐藏）
    els.updateBanner = el('div', 'wbs-update-banner');
    els.updateBanner.style.display = 'none';
    const updateClose = el('button', 'wbs-update-close', '×');
    updateClose.title = t('close');
    updateClose.addEventListener('click', () => { els.updateBanner.style.display = 'none'; });
    els.updateBanner.appendChild(updateClose);

    // body
    const body = el('div', 'wbs-body');
    const statusLine = el('div', 'wbs-status-line');
    els.status = el('span', 'wbs-status', t('statusIdle'));
    els.found = el('span', '', '');
    statusLine.append(els.status, els.found);

    const track = el('div', 'wbs-progress-track');
    els.fill = el('div', 'wbs-progress-fill');
    track.appendChild(els.fill);

    const row1 = el('div', 'wbs-btn-row');
    els.subPage = btn('subscribePage', t('subscribePage'), 'wbs-btn-green');
    els.subPages = btn('subscribePages', t('subscribePages'));
    els.unsub = btn('unsubscribePage', t('unsubscribePage'), 'wbs-btn-red');
    row1.append(els.subPage, els.subPages, els.unsub);

    // 订阅范围（序号），留空/0 表示当前页全部
    const rangeRow = el('div', 'wbs-range-row');
    rangeRow.append(el('span', '', t('rangeLabel')));
    els.rangeStart = document.createElement('input');
    els.rangeStart.type = 'number';
    els.rangeStart.min = '0';
    els.rangeStart.placeholder = '1';
    els.rangeStart.title = t('rangeHint');
    els.rangeEnd = document.createElement('input');
    els.rangeEnd.type = 'number';
    els.rangeEnd.min = '0';
    els.rangeEnd.placeholder = t('rangeAll');
    els.rangeEnd.title = t('rangeHint');
    rangeRow.append(els.rangeStart, el('span', '', '–'), els.rangeEnd);

    const row2 = el('div', 'wbs-btn-row');
    els.pause = btn('pause', t('pause'));
    els.cancel = btn('cancel', t('cancel'));
    els.retry = btn('retryFailed', t('retryFailed'));
    row2.append(els.pause, els.cancel, els.retry);

    els.log = el('div', 'wbs-log');

    els.settings = el('div', 'wbs-settings');
    body.append(statusLine, track, row1, rangeRow, row2, els.log, els.settings);

    const footer = el('div', 'wbs-footer', t('disclaimer'));

    root.append(header, els.updateBanner, body, footer);
    document.body.appendChild(root);
    setRunning(false);
    setupDrag(header);
    return root;
  }

  /* ---------- 面板拖动（header 区域可拖，按钮区域不触发） ---------- */

  const POS_KEY = 'wbs_panel_pos';

  function restorePosition() {
    if (!root) return;
    try {
      const raw = localStorage.getItem(POS_KEY);
      if (!raw) return;
      const pos = JSON.parse(raw);
      if (pos && typeof pos.left === 'number' && typeof pos.top === 'number') {
        // 切换为 left/top 定位，清除默认的 right/bottom
        root.style.right = 'auto';
        root.style.bottom = 'auto';
        // 边界校正（窗口尺寸可能已变）
        const maxLeft = window.innerWidth - root.offsetWidth;
        const maxTop = window.innerHeight - root.offsetHeight;
        const left = Math.max(0, Math.min(pos.left, maxLeft));
        const top = Math.max(0, Math.min(pos.top, maxTop));
        root.style.left = left + 'px';
        root.style.top = top + 'px';
      }
    } catch { /* localStorage 不可用时忽略 */ }
  }

  function setupDrag(header) {
    let dragging = false;
    let startX = 0, startY = 0, startLeft = 0, startTop = 0;

    const onMouseDown = (e) => {
      // 点到按钮/链接/输入框时不触发拖动
      if (e.target.closest('button, a, input, select, textarea')) return;
      dragging = true;
      const rect = root.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      startLeft = rect.left;
      startTop = rect.top;
      // 切换为 left/top 定位
      root.style.right = 'auto';
      root.style.bottom = 'auto';
      root.style.left = startLeft + 'px';
      root.style.top = startTop + 'px';
      e.preventDefault();
    };

    const onMouseMove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      let left = startLeft + dx;
      let top = startTop + dy;
      // 边界限制，不允许拖出可视区
      const maxLeft = window.innerWidth - root.offsetWidth;
      const maxTop = window.innerHeight - root.offsetHeight;
      left = Math.max(0, Math.min(left, maxLeft));
      top = Math.max(0, Math.min(top, maxTop));
      root.style.left = left + 'px';
      root.style.top = top + 'px';
    };

    const onMouseUp = () => {
      if (!dragging) return;
      dragging = false;
      try {
        const left = parseInt(root.style.left, 10) || 0;
        const top = parseInt(root.style.top, 10) || 0;
        localStorage.setItem(POS_KEY, JSON.stringify({ left, top }));
      } catch { /* 忽略存储失败 */ }
    };

    header.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  function setRunning(running) {
    els.subPage.disabled = running;
    els.subPages.disabled = running;
    els.unsub.disabled = running;
    els.pause.disabled = !running;
    els.cancel.disabled = !running;
    els.retry.disabled = running;
    els.rangeStart.disabled = running;
    els.rangeEnd.disabled = running;
  }

  window.WBS_Panel = {
    mount(version) { build(version); restorePosition(); },
    on(action, cb) { handlers[action] = cb; },
    getRange() {
      return {
        start: parseInt(els.rangeStart.value, 10) || 0,
        end: parseInt(els.rangeEnd.value, 10) || 0
      };
    },
    setRange(start, end) {
      els.rangeStart.value = start > 0 ? start : '';
      els.rangeEnd.value = end > 0 ? end : '';
    },
    showUpdate(latest, url) {
      els.updateBanner.innerHTML = '';
      const txt = el('span', '', t('updateAvailable', { v: latest }));
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = t('downloadUpdate');
      const close = el('button', 'wbs-update-close', '×');
      close.title = t('close');
      close.addEventListener('click', () => { els.updateBanner.style.display = 'none'; });
      els.updateBanner.append(txt, link, close);
      els.updateBanner.style.display = '';
    },
    setFound(n) {
      els.found.textContent = n > 0 ? `${n} ${t('itemsFound')}` : t('noItems');
    },
    setStatus(key, vars, warn) {
      els.status.textContent = t(key, vars);
      els.status.classList.toggle('wbs-warn', !!warn);
    },
    setProgress(done, total) {
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      els.fill.style.width = pct + '%';
    },
    setMode(mode) {
      els.mode.textContent = t(mode === 'unsubscribe' ? 'modeUnsubscribe' : 'modeSubscribe');
      els.mode.classList.toggle('wbs-mode-unsub', mode === 'unsubscribe');
    },
    setPauseLabel(paused) {
      els.pause.textContent = paused ? t('resume') : t('pause');
    },
    log(msg, cls, ts) {
      const d = new Date(ts || Date.now());
      const p = (n) => String(n).padStart(2, '0');
      const stamp = `[${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}]`;
      const line = el('div', cls ? 'wbs-log-' + cls : '');
      line.append(el('span', 'wbs-log-ts', stamp), document.createTextNode(' ' + msg));
      els.log.appendChild(line);
      while (els.log.children.length > 200) els.log.removeChild(els.log.firstChild);
      els.log.scrollTop = els.log.scrollHeight;
    },
    restoreLogs(entries) {
      for (const e of entries) this.log(e.msg, e.cls, e.ts);
    },
    clearLog() { els.log.innerHTML = ''; },
    renderSettings(s, onSave) {
      els.settings.innerHTML = '';
      const rows = [
        ['delayMin', t('settingDelay') + ' (min)', s.delayMin, 1, 30, 0.5],
        ['delayMax', t('settingDelay') + ' (max)', s.delayMax, 1, 60, 0.5],
        ['batchSize', t('settingBatch'), s.batchSize, 1, 50, 1],
        ['cooldownEnabled', t('settingCooldownEnabled'), s.cooldownEnabled, 'check'],
        ['cooldownMin', t('settingCooldown') + ' (min)', s.cooldownMin, 5, 300, 1],
        ['cooldownMax', t('settingCooldown') + ' (max)', s.cooldownMax, 5, 600, 1],
        ['maxRetries', t('settingRetry'), s.maxRetries, 0, 10, 1],
        ['maxPages', t('settingMaxPages'), s.maxPages, 1, 100, 1]
      ];
      for (const row of rows) {
        const [id, label, val, kind] = row;
        const l = document.createElement('label');
        if (kind === 'check') {
          l.classList.add('wbs-check-row');
          l.append(checkInput(id, val), el('span', '', label));
        } else {
          l.append(el('span', '', label), numInput(id, val, row[3], row[4], row[5]));
        }
        els.settings.appendChild(l);
      }
      const save = el('button', 'wbs-btn', t('save'));
      save.addEventListener('click', () => {
        const next = {};
        for (const [id, , , kind] of rows) {
          const input = document.getElementById('wbs-set-' + id);
          next[id] = kind === 'check' ? input.checked : parseFloat(input.value);
        }
        onSave(next);
        save.textContent = t('saved');
        setTimeout(() => { save.textContent = t('save'); }, 1200);
      });
      els.settings.appendChild(save);
    },
    setRunning
  };
})();
