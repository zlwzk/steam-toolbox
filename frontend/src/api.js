const BASE = '/api'

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function req(path, opts = {}, retries = 1) {
  let resp
  for (let attempt = 0; ; attempt += 1) {
    try {
      resp = await fetch(BASE + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      })
      break
    } catch (e) {
      // 本地后端未就绪（启动竞态）或端口被占用：有限重试，仍失败再给出明确中文提示
      if (attempt < retries) {
        await delay(500 * (attempt + 1))
        continue
      }
      throw new Error('无法连接本地服务：后端尚未就绪或端口被占用，请关闭软件后重新打开')
    }
  }
  if (!resp.ok) {
    const body = await resp.text()
    let error = body || `请求失败 ${resp.status}`
    try {
      const parsed = JSON.parse(body)
      if (typeof parsed.detail === "string") error = parsed.detail
      else if (typeof parsed.error === "string") error = parsed.error
    } catch { /* non-JSON server error */ }
    throw new Error(error)
  }
  return resp.json()
}

function qs(params) {
  const sp = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== '' && v != null) sp.set(k, v)
  })
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  version: () => req('/version'),
  sessionStatus: () => req('/session/status'),
  updateCheck: () => req('/update/check'),
  getAccount: () => req('/account'),
  saveAccount: (data) => req('/account', { method: 'POST', body: JSON.stringify(data) }),
  testAccount: (data) => req('/account/test', { method: 'POST', body: JSON.stringify(data) }),

  startScan: (kind = 'dlc', force = false) =>
    req(`/scan/start?kind=${kind}&force=${force ? 'true' : 'false'}`, { method: 'POST' }),
  pauseScan: () => req('/scan/pause', { method: 'POST' }),
  resumeScan: () => req('/scan/resume', { method: 'POST' }),
  progress: () => req('/scan/progress'),
  overview: () => req('/scan/overview'),
  logs: () => req('/logs'),
  clearLogs: () => req('/logs/clear', { method: 'POST' }),

  candidates: (params = {}) => req(`/candidates${qs(params)}`),
  summary: (itemType = 'dlc') => req(`/candidates/summary?item_type=${itemType}`),
  markCandidate: (appid, field, value) =>
    req(`/candidates/${appid}/mark`, { method: 'POST', body: JSON.stringify({ field, value }) }),

  freegames: (params = {}) => req(`/freegames${qs(params)}`),
  freeSummary: () => req('/freegames/summary'),
  markFreegame: (appid, field, value) =>
    req(`/freegames/${appid}/mark`, { method: 'POST', body: JSON.stringify({ field, value }) }),

  startClaim: (items) => req('/claim/start', { method: 'POST', body: JSON.stringify({ items }) }),
  resumeClaim: () => req('/claim/resume', { method: 'POST' }),
  claimProgress: () => req('/claim/progress'),
  claimRecords: () => req('/claim/records'),
  login: () => req('/claim/login', { method: 'POST' }),

  // 创意工坊批量订阅 / 退订
  wsStart: (data) => req('/workshop/start', { method: 'POST', body: JSON.stringify(data) }),
  wsProgress: () => req('/workshop/progress'),
  wsItems: (status = '') => req(`/workshop/items${qs({ status })}`),
  wsPause: () => req('/workshop/pause', { method: 'POST' }),
  wsCancel: () => req('/workshop/cancel', { method: 'POST' }),
  wsRetry: () => req('/workshop/retry-failed', { method: 'POST' }),
  wsMark: (pid, field, value) => req(`/workshop/${pid}/mark`, { method: 'POST', body: JSON.stringify({ field, value }) }),
  wsClear: () => req('/workshop/clear', { method: 'POST' }),

  // 库清理
  clAnalyze: (rule) => req('/cleaner/analyze', { method: 'POST', body: JSON.stringify(rule) }),
  clProgress: () => req('/cleaner/progress'),
  clItems: (status = '') => req(`/cleaner/items${qs({ status })}`),
  clMark: (appid, field, value) => req(`/cleaner/${appid}/mark`, { method: 'POST', body: JSON.stringify({ field, value }) }),
  clRemove: (appids) => req('/cleaner/remove', { method: 'POST', body: JSON.stringify({ appids }) }),
  clClear: () => req('/cleaner/clear', { method: 'POST' }),

  getSettings: () => req('/settings'),
  saveSettings: (data) => req('/settings', { method: 'PUT', body: JSON.stringify({ data }) }),
  schedulerStatus: () => req('/settings/scheduler-status'),

  // 更新监控
  monOverview: () => req('/monitor/overview'),
  monGames: () => req('/monitor/games'),
  monAddGame: (data) => req('/monitor/games', { method: 'POST', body: JSON.stringify(data) }),
  monRemoveGame: (appid) => req(`/monitor/games/${appid}`, { method: 'DELETE' }),
  monMods: () => req('/monitor/mods'),
  monAddMod: (data) => req('/monitor/mods', { method: 'POST', body: JSON.stringify(data) }),
  monRemoveMod: (fileId) => req(`/monitor/mods/${fileId}`, { method: 'DELETE' }),
  monRules: () => req('/monitor/rules'),
  monAddRule: (data) => req('/monitor/rules', { method: 'POST', body: JSON.stringify(data) }),
  monUpdateRule: (id, data) => req(`/monitor/rules/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  monRemoveRule: (id) => req(`/monitor/rules/${id}`, { method: 'DELETE' }),
  monEvents: (params = {}) => req(`/monitor/events${qs(params)}`),
  monReadEvents: (ids) => req('/monitor/events/read', { method: 'POST', body: JSON.stringify({ ids: ids || [] }) }),
  monCheck: () => req('/monitor/check', { method: 'POST' }),
  monProgress: () => req('/monitor/progress'),
  monSubscribe: (items) => req('/monitor/subscribe', { method: 'POST', body: JSON.stringify({ items }) }),
  monSettings: () => req('/monitor/settings'),
  monSaveSettings: (data) => req('/monitor/settings', { method: 'PUT', body: JSON.stringify(data) }),
  loginStatus: () => req('/claim/login/status'),

  exportUrl: (kind, params = {}) => `${BASE}/${kind}/export.csv${qs(params)}`,
}
