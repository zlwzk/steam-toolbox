/* i18n.js — 中英双语，按 Steam_Language cookie / 浏览器语言自动切换 */
(function () {
  'use strict';

  const MESSAGES = {
    en: {
      panelTitle: 'Batch Subscribe',
      itemsFound: 'items on this page',
      subscribePage: 'Subscribe This Page',
      subscribePages: 'All Pages (Auto)',
      unsubscribePage: 'Unsubscribe This Page',
      pause: 'Pause',
      resume: 'Resume',
      cancel: 'Cancel',
      retryFailed: 'Retry Failed',
      settings: 'Settings',
      log: 'Log',
      progress: 'Progress',
      statusIdle: 'Idle',
      statusRunning: 'Running',
      statusPaused: 'Paused',
      statusCooldown: 'Cooling down',
      statusBackoff: 'Rate-limited, waiting',
      statusDone: 'Done',
      statusCancelled: 'Cancelled',
      notLoggedIn: 'You are not logged in to Steam. Please log in first.',
      noItems: 'No workshop items found on this page.',
      unsubConfirm: 'This will UNSUBSCRIBE all items on this page. Are you sure?',
      doneSummary: 'Finished. Success: {ok}, Failed: {fail}',
      nextPage: 'Moving to page {p}…',
      nextPageProbe: 'Pagination not detected, probing page {p}…',
      lastPage: 'No more pages. Auto mode finished.',
      maxPagesHit: 'Reached the auto page-turn limit ({n} pages). Stopped.',
      noFailed: 'No failed items to retry.',
      authOk: 'Steam login detected.',
      waitingRetry: 'Retry in {s}s (attempt {n})…',
      cooldownMsg: 'Cooldown {s}s (auto-pause freezes the timer)…',
      cooldownDisabled: 'Batch cooldown is DISABLED — faster but easier to hit Steam limits.',
      settingCooldownEnabled: 'Enable batch cooldown',
      itemOk: 'OK',
      itemFail: 'FAIL',
      settingDelay: 'Delay between items (sec)',
      settingBatch: 'Items per batch',
      settingCooldown: 'Batch cooldown (sec)',
      settingRetry: 'Max retries per item',
      settingMaxPages: 'Auto page-turn limit (pages)',
      exportLog: 'Export Log',
      collapse: 'Collapse',
      refresh: 'Refresh scan & settings',
      checkUpdate: 'Check for updates',
      updateAvailable: 'New version v{v} available!',
      downloadUpdate: 'Download',
      upToDate: 'You are on the latest version (v{v}).',
      updateCheckFailed: 'Update check failed: ',
      rangeLabel: 'Items No.',
      rangeAll: 'end',
      rangeHint: '1-based positions on the current page; blank/0 = from 1 / to the last',
      rangeApply: 'Processing items {a}–{b} ({n} total).',
      rangeAutoFixed: 'Invalid range — start/end swapped automatically.',
      progressItem: 'Processing {i}/{total}…',
      pageStart: 'Starting page {p}…',
      pageDone: 'Page {p} done (this page: {ok} ok, {fail} failed).',
      refreshed: 'Refreshed. {n} items found on this page.',
      save: 'Save',
      saved: 'Saved.',
      disclaimer: 'For personal use only. Data stays in your browser.',
      modeSubscribe: 'SUBSCRIBE',
      modeUnsubscribe: 'UNSUBSCRIBE',
      close: 'Close'
    },
    zh: {
      panelTitle: '批量订阅',
      itemsFound: '个物品',
      subscribePage: '订阅本页全部',
      subscribePages: '全部页（自动翻页）',
      unsubscribePage: '退订本页全部',
      pause: '暂停',
      resume: '继续',
      cancel: '取消',
      retryFailed: '重试失败项',
      settings: '设置',
      log: '日志',
      progress: '进度',
      statusIdle: '空闲',
      statusRunning: '进行中',
      statusPaused: '已暂停',
      statusCooldown: '批次冷却中',
      statusBackoff: '触发限制，等待中',
      statusDone: '已完成',
      statusCancelled: '已取消',
      notLoggedIn: '未登录 Steam，请先登录后再使用。',
      noItems: '本页未发现创意工坊物品。',
      unsubConfirm: '即将退订本页全部物品，确定继续吗？',
      doneSummary: '完成。成功 {ok} 个，失败 {fail} 个。',
      nextPage: '正在前往第 {p} 页…',
      nextPageProbe: '未探测到分页，试探前往第 {p} 页…',
      lastPage: '已到最后一页，自动翻页结束。',
      maxPagesHit: '已达自动翻页上限（{n} 页），自动停止。',
      noFailed: '没有需要重试的失败项。',
      authOk: '已检测到 Steam 登录。',
      waitingRetry: '{s} 秒后重试（第 {n} 次）…',
      cooldownMsg: '批次冷却中，剩余 {s} 秒（暂停时计时冻结）…',
      cooldownDisabled: '批次冷却已关闭——速度更快但更容易触发 Steam 限制，请谨慎。',
      settingCooldownEnabled: '启用批次冷却',
      itemOk: '成功',
      itemFail: '失败',
      settingDelay: '每项间隔（秒）',
      settingBatch: '每批数量',
      settingCooldown: '批次冷却（秒）',
      settingRetry: '单项最大重试次数',
      settingMaxPages: '自动翻页上限（页）',
      exportLog: '导出日志',
      collapse: '折叠面板',
      refresh: '刷新扫描与设置',
      checkUpdate: '检查更新',
      updateAvailable: '发现新版本 v{v}！',
      downloadUpdate: '前往下载',
      upToDate: '当前已是最新版本（v{v}）。',
      updateCheckFailed: '更新检查失败：',
      rangeLabel: '序号',
      rangeAll: '末',
      rangeHint: '当前页的 1 基序号，留空或 0 表示从第 1 个开始 / 到最后一个结束',
      rangeApply: '本次处理第 {a}–{b} 个，共 {n} 项。',
      rangeAutoFixed: '范围无效，已自动交换起止序号。',
      progressItem: '正在处理 {i}/{total}…',
      pageStart: '开始处理第 {p} 页…',
      pageDone: '第 {p} 页已完成（本页成功 {ok}，失败 {fail}）。',
      refreshed: '已刷新，当前页发现 {n} 个物品。',
      save: '保存',
      saved: '已保存。',
      disclaimer: '仅限个人使用，数据保存在本地浏览器。',
      modeSubscribe: '订阅',
      modeUnsubscribe: '退订',
      close: '关闭'
    }
  };

  function detectLang() {
    const m = document.cookie.match(/(?:^|;\s*)Steam_Language=([^;]+)/);
    const lang = (m ? m[1] : (navigator.language || 'en')).toLowerCase();
    return lang.startsWith('zh') || lang.includes('schinese') || lang.includes('tchinese') ? 'zh' : 'en';
  }

  const lang = detectLang();
  const dict = MESSAGES[lang];

  window.WBS_I18N = {
    lang,
    t(key, vars) {
      let s = dict[key] || MESSAGES.en[key] || key;
      if (vars) {
        for (const k of Object.keys(vars)) {
          s = s.replace('{' + k + '}', String(vars[k]));
        }
      }
      return s;
    }
  };
})();
