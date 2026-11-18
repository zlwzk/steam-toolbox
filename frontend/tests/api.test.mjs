// 前端核心逻辑回归测试：使用 Node 内置 test runner（node:test），零新增依赖。
// 覆盖：请求层安全方法重试 / 错误归一化、启动页 key 安全解析。
// 运行：npm test（见 package.json scripts）

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ---- 动态加载被测模块（api.js / tabState.js 为 ESM 源码，直接 import） ----
const { req } = await import('../src/api.js')
const { resolveInitialTab, readStoredTab, VALID_TABS, DEFAULT_TAB } = await import('../src/tabState.js')

// ---------- 请求层：只对安全读取方法做有限重试 ----------

test('GET 请求在瞬时网络错误后有限重试', async () => {
  let calls = 0
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => {
    calls += 1
    if (calls < 3) throw new TypeError('fetch failed')
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }
  try {
    const out = await req('/health')
    assert.deepEqual(out, { ok: true })
    assert.equal(calls, 3, '前两次失败后第三次成功')
  } finally {
    globalThis.fetch = origFetch
  }
})

test('POST 请求失败后不自动重试（避免重复执行外部操作）', async () => {
  let calls = 0
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => {
    calls += 1
    throw new TypeError('fetch failed')
  }
  try {
    await assert.rejects(
      () => req('/claim/start', { method: 'POST', body: '{}' }),
      /无法连接本地服务/
    )
    assert.equal(calls, 1, 'POST 必须只调用一次，不重试')
  } finally {
    globalThis.fetch = origFetch
  }
})

test('PUT / DELETE 同样不重试', async () => {
  for (const method of ['PUT', 'DELETE']) {
    let calls = 0
    const origFetch = globalThis.fetch
    globalThis.fetch = async () => {
      calls += 1
      throw new TypeError('fetch failed')
    }
    try {
      await assert.rejects(() => req('/settings', { method, body: '{}' }))
      assert.equal(calls, 1, `${method} 不应重试`)
    } finally {
      globalThis.fetch = origFetch
    }
  }
})

test('GET 收到 4xx 时不重试并透出 FastAPI detail', async () => {
  let calls = 0
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => {
    calls += 1
    return new Response(JSON.stringify({ detail: '仅允许本机访问' }), { status: 403 })
  }
  try {
    await assert.rejects(() => req('/health'), /仅允许本机访问/)
    assert.equal(calls, 1, '4xx 不重试')
  } finally {
    globalThis.fetch = origFetch
  }
})

test('GET 收到 429 时重试（服务端瞬时错误）', async () => {
  let calls = 0
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => {
    calls += 1
    if (calls < 2) return new Response('too many', { status: 429 })
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }
  try {
    const out = await req('/health')
    assert.deepEqual(out, { ok: true })
    assert.equal(calls, 2, '429 应重试一次后成功')
  } finally {
    globalThis.fetch = origFetch
  }
})

test('FastAPI 422 校验错误数组被归一化为可读文案', async () => {
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: [
      { loc: ['query', 'limit'], msg: 'Input should be greater than or equal to 1' },
    ],
  }), { status: 422 })
  try {
    await assert.rejects(() => req('/monitor/events?limit=0'), /limit.*greater than or equal to 1/)
  } finally {
    globalThis.fetch = origFetch
  }
})

test('非 JSON 错误体不抛解析错误，返回可读文案', async () => {
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('<html>502 Bad Gateway</html>', {
    status: 502,
    headers: { 'content-type': 'text/html' },
  })
  try {
    await assert.rejects(() => req('/health'), /502 Bad Gateway/)
  } finally {
    globalThis.fetch = origFetch
  }
})

test('空成功响应返回 null 而不是抛错', async () => {
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('', { status: 200 })
  try {
    assert.equal(await req('/health'), null)
  } finally {
    globalThis.fetch = origFetch
  }
})

// ---------- 请求超时（AbortController） ----------

test('请求超时被转换为可读错误', async () => {
  const origFetch = globalThis.fetch
  // 模拟超时：fetch 拒绝并带 AbortError 名称
  globalThis.fetch = async () => {
    const e = new Error('This operation was aborted')
    e.name = 'AbortError'
    throw e
  }
  try {
    await assert.rejects(() => req('/health'), /请求超时/)
  } finally {
    globalThis.fetch = origFetch
  }
})

// ---------- 启动页 key 安全读取 ----------

test('合法 key 直接返回', () => {
  assert.equal(resolveInitialTab('monitor'), 'monitor')
  assert.equal(resolveInitialTab('dashboard'), 'dashboard')
})

test('未知 key 回退总览（不白屏）', () => {
  assert.equal(resolveInitialTab('no-such-page'), DEFAULT_TAB)
  assert.equal(resolveInitialTab(''), DEFAULT_TAB)
  assert.equal(resolveInitialTab(null), DEFAULT_TAB)
  assert.equal(resolveInitialTab(undefined), DEFAULT_TAB)
})

test('collections 在未激活完整版时回退总览', () => {
  assert.equal(resolveInitialTab('collections', { proUnlocked: false }), DEFAULT_TAB)
  assert.equal(resolveInitialTab('collections', { proUnlocked: true }), 'collections')
})

test('存储不可用时读取返回 null 并回退总览', () => {
  const brokenStorage = {
    getItem() { throw new Error('SecurityError') },
  }
  assert.equal(readStoredTab(brokenStorage, 'steam_dlc_tab'), null)
  assert.equal(readStoredTab(null, 'steam_dlc_tab'), null)
  assert.equal(resolveInitialTab(readStoredTab(brokenStorage, 'x')), DEFAULT_TAB)
})

test('合法 key 集合与 App 组件映射一致', () => {
  // 抽取 App.vue 的 comps 键集合，与 VALID_TABS 对齐校验
  const appVue = readFileSync(path.join(__dirname, '../src/App.vue'), 'utf8')
  const m = appVue.match(/const comps = \{([\s\S]*?)\}/)
  assert.ok(m, 'App.vue 中应存在 comps 映射')
  const keys = [...m[1].matchAll(/^\s*(\w+):\s*\w+/gm)].map((x) => x[1])
  assert.deepEqual([...keys].sort(), [...VALID_TABS].sort())
})
