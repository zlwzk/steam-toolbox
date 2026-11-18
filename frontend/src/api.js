const BASE = '/api'

// 默认超时（毫秒）：本地服务响应慢时给出明确提示，避免界面无限转圈
const DEFAULT_TIMEOUT_MS = 30000
// 仅安全读取方法允许有限自动重试；POST/PUT/DELETE 默认不重试，避免重复创建任务或重复执行外部操作
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const MAX_SAFE_RETRIES = 2
// 安全读取请求在这些情况下才重试：网络错误/超时，或 429/5xx 服务端瞬时错误
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504])

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function methodOf(opts) {
  return String((opts && opts.method) || 'GET').toUpperCase()
}

/** 带超时的 fetch；超时通过 AbortController 中断 */
async function fetchWithTimeout(path, opts, timeoutMs) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(BASE + path, {
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      ...opts,
    })
  } finally {
    clearTimeout(timer)
  }
}

/** 把错误响应体归一化为可读中文文案：兼容 FastAPI 字符串 detail、422 校验错误数组、空响应与非 JSON 内容 */
async function extractError(resp) {
  let body = ''
  try {
    body = await resp.text()
  } catch { /* 响应体读取失败时按状态码兜底 */ }
  if (body) {
    try {
      const parsed = JSON.parse(body)
      if (typeof parsed.detail === 'string') return parsed.detail
      if (Array.isArray(parsed.detail)) {
        const msgs = parsed.detail
          .map((d) => {
            const loc = d && Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''
            const m = (d && d.msg) || (typeof d === 'string' ? d : '')
            return [loc, m].filter(Boolean).join(' ')
          })
          .filter(Boolean)
        if (msgs.length) return msgs.join('；')
      }
      if (typeof parsed.error === 'string') return parsed.error
      if (typeof parsed.message === 'string') return parsed.message
    } catch { /* non-JSON server error */ }
    const oneLine = body.replace(/\s+/g, ' ').trim()
    if (oneLine) return oneLine.length > 200 ? `${oneLine.slice(0, 200)}…` : oneLine
  }
  return `请求失败 ${resp.status}`
}

function httpError(resp, message) {
  const err = new Error(message)
  err.status = resp.status
  return err
}

function isAbortError(e) {
  return e && (e.name === 'AbortError' || /aborted/i.test(String(e.message || '')))
}

/**
 * 统一请求入口。
 * - 只对安全读取方法（GET/HEAD/OPTIONS）做有限重试；写操作方法不自动重试。
 * - 超时、连接失败、可读错误文案归一化。
 */
export async function req(path, opts = {}) {
  const method = methodOf(opts)
  const safe = SAFE_METHODS.has(method)
  const maxAttempts = safe ? 1 + MAX_SAFE_RETRIES : 1
  let lastErr = null

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const resp = await fetchWithTimeout(path, opts, DEFAULT_TIMEOUT_MS)
      if (!resp.ok) throw httpError(resp, await extractError(resp))
      if (resp.status === 204) return null
      const text = await resp.text()
      if (!text) return null
      try {
        return JSON.parse(text)
      } catch {
        throw new Error('服务返回了无法解析的内容，请查看运行日志')
      }
    } catch (e) {
      lastErr = e
      const canRetry = safe && attempt < maxAttempts - 1
      if (!canRetry) break
      // 网络错误/超时（无 status）或 429/5xx 才重试；4xx 响应错误不重试
      const transient = e.status === undefined || RETRYABLE_STATUS.has(e.status)
      if (!transient) break
      await delay(500 * (attempt + 1))
    }
  }

  if (lastErr && lastErr.status === undefined) {
    if (isAbortError(lastErr)) {
      throw new Error('请求超时：本地服务响应过慢，请稍后重试或查看运行日志')
    }
    throw new Error('无法连接本地服务：后端尚未就绪或端口被占用，请关闭软件后重新打开')
  }
  throw lastErr || new Error('请求失败')
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

  // 完整版激活态（本机持久化）
  proStatus: () => req('/pro/status'),
  proUnlock: () => req('/pro/unlock', { method: 'POST' }),

  // 库自动分类（完整版）
  colStatus: () => req('/collections/status'),
  colPlan: (data) => req('/collections/plan', { method: 'POST', body: JSON.stringify(data) }),
  colWrite: (data) => req('/collections/write', { method: 'POST', body: JSON.stringify(data) }),
  colRestore: (data) => req('/collections/restore', { method: 'POST', body: JSON.stringify(data) }),

  exportUrl: (kind, params = {}) => `${BASE}/${kind}/export.csv${qs(params)}`,
}
