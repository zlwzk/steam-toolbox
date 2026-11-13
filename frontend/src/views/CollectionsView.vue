<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const { msg, ok, err, info, errText } = useMsg()

const status = ref({ steam: null, accounts: [], running: false, backup: null })
const accountid = ref('')
const single = ref(false)
const maxcats = ref(5)

const cats = ref({})
const games = ref([])
const stats = ref({ games: 0, links: 0, avg: 0, per_category: {}, tags_count: 0 })
const who = ref('')
const loading = ref(false)
const writing = ref(false)

const query = ref('')
const sel = ref('*')
const dirty = ref({}) // appid -> true，被手动改过

const LS_KEY = 'steam-cat-plan-multi'

// 分类展示名：去掉开头两位编号前缀与结尾的「-」
function displayName(name) {
  return String(name || '').replace(/^\d{2}-/, '').replace(/-$/, '')
}

const catList = computed(() =>
  Object.entries(cats.value).map(([num, name]) => ({ num: Number(num), name: displayName(name) }))
)

// 每个分类的主分类数 / 兼属数
const catCounts = computed(() => {
  const main = {}, side = {}
  games.value.forEach((g) => {
    const all = g.all || []
    all.forEach((c, i) => {
      if (i === 0) main[c] = (main[c] || 0) + 1
      else side[c] = (side[c] || 0) + 1
    })
  })
  return { main, side }
})

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return games.value.filter((g) => {
    if (sel.value !== '*' && !(g.all || []).includes(Number(sel.value))) return false
    if (!q) return true
    const hay = [g.cn || '', g.n || '', ...(g.t || [])].join(' ').toLowerCase()
    return hay.includes(q)
  })
})

const liveStats = computed(() => {
  const links = games.value.reduce((s, g) => s + (g.all || []).length, 0)
  return { games: games.value.length, links, avg: games.value.length ? (links / games.value.length).toFixed(2) : '0' }
})

function persistLocal() {
  try {
    const data = Object.fromEntries(games.value.map((g) => [String(g.id), g.all]))
    localStorage.setItem(LS_KEY, JSON.stringify(data))
  } catch { /* 存储不可用时忽略 */ }
}

function loadLocalOverrides() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

async function loadStatus() {
  try {
    status.value = await api.colStatus()
    if (status.value.accounts.length) {
      accountid.value = accountid.value || status.value.accounts[0].accountid
    }
  } catch (e) { err('检测 Steam 环境失败：' + errText(e)) }
}

async function loadPlan() {
  loading.value = true
  try {
    const payload = { accountid: accountid.value || null, maxcats: Number(maxcats.value), single: single.value }
    const r = await api.colPlan(payload)
    cats.value = r.cats || {}
    stats.value = r.stats || stats.value
    who.value = r.who || ''
    const local = loadLocalOverrides()
    games.value = (r.games || []).map((g) => {
      const saved = local[String(g.id)]
      return saved && Array.isArray(saved) && saved.length ? { ...g, all: saved.map(Number) } : g
    })
    dirty.value = {}
  } catch (e) { err('生成分类方案失败：' + errText(e)); games.value = [] }
  finally { loading.value = false }
}

function markDirty(g) {
  dirty.value[String(g.id)] = true
}

function removeChip(g, idx) {
  if (g.all.length <= 1) { info('至少保留一个分类'); return }
  g.all.splice(idx, 1)
  markDirty(g)
  persistLocal()
}

function addCat(g, num) {
  if (num == null) return
  if (g.all.includes(num)) return
  g.all.push(num)
  markDirty(g)
  persistLocal()
}

function availableCats(g) {
  return catList.value.filter((c) => !g.all.includes(c.num))
}

async function writePlan() {
  if (!games.value.length) { err('方案为空，没有可写入的游戏'); return }
  if (status.value.running) { err('Steam 还在运行，请完全退出后再写入'); return }
  const okWrite = confirm(
    `即将把 ${games.value.length} 个游戏的分类写入 Steam 本地云端收藏夹。\n` +
    '已有同名收藏夹会被更新，你自己建的收藏夹不受影响；写入前会自动备份，可随时还原。\n\n确认写入？（请先完全退出 Steam）'
  )
  if (!okWrite) return
  writing.value = true
  try {
    const r = await api.colWrite({ accountid: accountid.value, games: games.value })
    if (r.ok) {
      ok(`写入完成：${r.rows.length} 个收藏夹，备份：${r.backup || '—'}`)
      await loadStatus()
    } else err(r.error || '写入失败')
  } catch (e) { err('写入失败：' + errText(e)) }
  finally { writing.value = false }
}

async function restoreBackup() {
  if (status.value.running) { err('Steam 还在运行，请完全退出后再还原'); return }
  if (!confirm('确定还原到最近一次备份？当前收藏夹归属会被备份覆盖。')) return
  try {
    const r = await api.colRestore({ accountid: accountid.value })
    if (r.ok) { ok('已从备份还原：' + r.backup); await loadStatus() }
    else err(r.error || '还原失败')
  } catch (e) { err('还原失败：' + errText(e)) }
}

function exportJson() {
  const out = {}
  games.value.forEach((g) => { if (dirty.value[String(g.id)]) out[String(g.id)] = g.all })
  const text = JSON.stringify(out, null, 2)
  if (!Object.keys(out).length) { info('还没有手动调整过分类'); return text }
  return text
}

async function copyExport() {
  const text = exportJson()
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ok('覆盖配置已复制到剪贴板')
  } catch {
    // 剪贴板不可用：回退为选中文本，用户手动 Ctrl+C
    const area = document.createElement('textarea')
    area.value = text
    document.body.appendChild(area)
    area.select()
    try { document.execCommand('copy'); ok('覆盖配置已复制') }
    catch { info('已选中文本，请按 Ctrl+C 复制') }
    area.remove()
  }
}

onMounted(() => { loadStatus().then(loadPlan) })
</script>

<template>
  <div class="card">
    <div class="row" style="align-items:end; gap:16px; flex-wrap:wrap;">
      <div class="field" style="margin:0;">
        <label>Steam 账号</label>
        <select v-model="accountid" @change="loadPlan">
          <option v-for="a in status.accounts" :key="a.accountid" :value="a.accountid">
            {{ a.name }}（{{ a.accountid }}）
          </option>
        </select>
      </div>
      <div class="field" style="margin:0;">
        <label>每游戏最多分类数</label>
        <select v-model.number="maxcats" :disabled="single">
          <option :value="1">1（只归一类）</option>
          <option :value="2">2</option>
          <option :value="3">3</option>
          <option :value="4">4</option>
          <option :value="5">5</option>
        </select>
      </div>
      <label style="padding-bottom:10px;"><input type="checkbox" v-model="single" /> 互斥模式（只归一类）</label>
      <button class="primary" :disabled="loading" @click="loadPlan">{{ loading ? '分析中…' : '重新生成方案' }}</button>
      <button class="ghost" :disabled="writing" :class="{ danger: status.running }" @click="writePlan">
        {{ writing ? '写入中…' : '备份并写入 Steam' }}
      </button>
      <button @click="restoreBackup" :disabled="!status.backup">还原最近备份</button>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <div class="muted" v-if="!status.steam" style="margin-top:12px;">
      未检测到 Steam 安装目录；请确认 Steam 已安装并至少登录过一次。
    </div>
    <div class="warn-bar" v-else-if="status.running" style="margin-top:12px;">
      Steam 当前正在运行：预览与调整不受影响，但写入 / 还原前需要完全退出 Steam（托盘图标右键 → 退出）。
    </div>
    <div class="muted" v-if="status.backup" style="margin-top:8px;">最近备份：{{ status.backup }}</div>

    <div class="stats" style="margin-top:16px;">
      <div class="stat">游戏总数<b>{{ liveStats.games }}</b></div>
      <div class="stat">归属关系<b>{{ liveStats.links }}</b></div>
      <div class="stat">平均分类<b>{{ liveStats.avg }}</b></div>
      <div class="stat" v-if="who">当前账号<b>{{ who }}</b></div>
    </div>

    <div class="cat-layout">
      <aside class="cat-side">
        <div class="cat-side-title">分类</div>
        <button :class="{ active: sel === '*' }" @click="sel = '*'">看全部 {{ games.length }}</button>
        <button v-for="c in catList" :key="c.num" :class="{ active: sel === String(c.num) }" @click="sel = String(c.num)">
          <span>{{ c.name }}</span>
          <span class="cat-badge">
            <b>{{ catCounts.main[c.num] || 0 }}</b><span v-if="catCounts.side[c.num]">+{{ catCounts.side[c.num] }}</span>
          </span>
        </button>
      </aside>

      <section class="cat-main">
        <div class="row" style="margin-bottom:12px; gap:12px;">
          <input v-model="query" placeholder="搜索游戏名 / 标签…" style="padding:9px 12px;border:1px solid var(--border);border-radius:8px;min-width:220px;" />
          <span class="muted">匹配 {{ filtered.length }} 个</span>
        </div>

        <div v-if="filtered.length" class="cat-rows">
          <div v-for="g in filtered" :key="g.id" class="cat-row" :class="{ dirty: dirty[g.id] }">
            <div class="cat-row-info">
              <div class="game-name">{{ g.cn || g.n || `#${g.id}` }}</div>
              <div class="muted en" v-if="g.cn && g.n">{{ g.n }}</div>
              <div class="muted" v-if="g.y">{{ g.y }}</div>
            </div>
            <div class="cat-chips">
              <span v-for="(c, i) in g.all" :key="c" class="chip" :class="{ main: i === 0 }">
                {{ displayName(cats[c]) }}
                <button class="chip-x" title="移出该分类" @click="removeChip(g, i)">×</button>
              </span>
              <select class="chip-add" @change="addCat(g, Number($event.target.value)); $event.target.value = ''">
                <option value="" disabled>+ 加分类</option>
                <option v-for="c in availableCats(g)" :key="c.num" :value="c.num">{{ c.name }}</option>
              </select>
            </div>
          </div>
        </div>
        <div v-else class="muted" style="text-align:center;padding:30px;">没有匹配的游戏。</div>
      </section>
    </div>

    <div class="cat-dock" v-if="Object.keys(dirty).length">
      <div>已手动调整 {{ Object.keys(dirty).length }} 个游戏的归属</div>
      <button class="ghost" @click="copyExport">复制覆盖配置 JSON</button>
    </div>
  </div>
</template>
