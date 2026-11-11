/* background.js — action 角标 + 登录态查询 + 更新检测 */
'use strict';

const UPDATE_API = 'https://api.github.com/repos/zlwzk/steam-toolbox/releases/latest';
const UPDATE_KEY = 'wbs_update';
const UPDATE_TTL_MS = 12 * 60 * 60 * 1000; // 12 小时内不重复请求

function norm(v) {
  const m = String(v || '').match(/(\d+)\.(\d+)\.(\d+)/);
  return m ? [+m[1], +m[2], +m[3]] : [0, 0, 0];
}

function isNewer(latest, current) {
  const a = norm(latest), b = norm(current);
  return a[0] !== b[0] ? a[0] > b[0]
    : a[1] !== b[1] ? a[1] > b[1]
    : a[2] > b[2];
}

async function checkUpdate(force) {
  const current = chrome.runtime.getManifest().version;
  const now = Date.now();

  if (!force) {
    const cached = (await chrome.storage.local.get(UPDATE_KEY))[UPDATE_KEY];
    if (cached && cached.checkedAt && now - cached.checkedAt < UPDATE_TTL_MS) {
      return { ...cached, current, cached: true };
    }
  }

  try {
    const resp = await fetch(UPDATE_API + '?t=' + now, {
      headers: { Accept: 'application/vnd.github+json' }
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    const latest = (data.tag_name || '').replace(/^v/, '');
    const info = {
      current,
      latest,
      hasUpdate: isNewer(latest, current),
      url: data.html_url || 'https://github.com/zlwzk/steam-toolbox/releases/latest',
      checkedAt: now,
      error: null
    };
    await chrome.storage.local.set({ [UPDATE_KEY]: info });
    return info;
  } catch (e) {
    // 失败时回退缓存（可能为离线/受限网络环境）
    const cached = (await chrome.storage.local.get(UPDATE_KEY))[UPDATE_KEY];
    if (cached) return { ...cached, current, cached: true };
    return { current, latest: '', hasUpdate: false, url: '', checkedAt: now, error: String(e) };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== 'object') return;

  if (msg.type === 'wbs:badge') {
    const text = msg.text || '';
    chrome.action.setBadgeText({ text });
    if (text) {
      chrome.action.setBadgeBackgroundColor({ color: msg.color || '#5c7e10' });
    }
    return;
  }

  // steamLoginSecure 是 HttpOnly Cookie，内容脚本的 document.cookie 读不到，
  // 必须通过 chrome.cookies API 在后台查询。
  if (msg.type === 'wbs:auth') {
    (async () => {
      try {
        const [login, sess] = await Promise.all([
          chrome.cookies.get({ url: 'https://steamcommunity.com', name: 'steamLoginSecure' }),
          chrome.cookies.get({ url: 'https://steamcommunity.com', name: 'sessionid' })
        ]);
        sendResponse({
          loggedIn: !!(login && login.value),
          sessionId: sess && sess.value ? sess.value : null
        });
      } catch (e) {
        sendResponse({ loggedIn: null, sessionId: null, error: String(e) });
      }
    })();
    return true; // 异步 sendResponse
  }

  if (msg.type === 'wbs:checkUpdate') {
    checkUpdate(!!msg.force).then(sendResponse).catch((e) => {
      sendResponse({ current: chrome.runtime.getManifest().version, error: String(e) });
    });
    return true;
  }
});
