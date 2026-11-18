// 启动页 key 的安全读取与校验。
// localStorage 可能被禁用、内容被篡改或属于已下线功能；无效时回退总览，避免白屏。

export const DEFAULT_TAB = 'dashboard'

/** 全部合法页面 key（与 App.vue 的 comps 映射保持一致） */
export const VALID_TABS = [
  'dashboard',
  'account',
  'scan',
  'candidates',
  'freegames',
  'workshop',
  'monitor',
  'cleaner',
  'collections',
  'claim',
  'settings',
]

/**
 * 从存储值解析启动页 key：
 * - 存储不可用 / 读取异常 → 总览
 * - 值不在合法集合内（含完整版未激活时的 collections）→ 总览
 */
export function resolveInitialTab(stored, options = {}) {
  const { proUnlocked = false } = options
  try {
    const key = typeof stored === 'string' ? stored.trim() : ''
    if (!key || !VALID_TABS.includes(key)) return DEFAULT_TAB
    if (key === 'collections' && !proUnlocked) return DEFAULT_TAB
    return key
  } catch {
    return DEFAULT_TAB
  }
}

/** 安全读取 localStorage 指定键；存储不可用或抛错时返回 null */
export function readStoredTab(storage, key) {
  try {
    return storage ? storage.getItem(key) : null
  } catch {
    return null
  }
}
