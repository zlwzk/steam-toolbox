<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import AccountView from './views/AccountView.vue'
import ScanView from './views/ScanView.vue'
import CandidatesView from './views/CandidatesView.vue'
import FreeGamesView from './views/FreeGamesView.vue'
import WorkshopView from './views/WorkshopView.vue'
import MonitorView from './views/MonitorView.vue'
import CleanerView from './views/CleanerView.vue'
import CollectionsView from './views/CollectionsView.vue'
import ClaimView from './views/ClaimView.vue'
import SettingsView from './views/SettingsView.vue'
import DashboardView from './views/DashboardView.vue'
import LogPanel from './views/LogPanel.vue'

const tabs = [
  { key: 'dashboard', label: '总览' },
  { key: 'account', label: '账号绑定' },
  { key: 'scan', label: 'DLC 扫描' },
  { key: 'candidates', label: 'DLC 清单' },
  { key: 'freegames', label: '喜加一' },
  { key: 'workshop', label: '工坊订阅' },
  { key: 'monitor', label: '更新监控' },
  { key: 'cleaner', label: '库清理' },
  { key: 'collections', label: '库分类', pro: true },
  { key: 'claim', label: '领取记录' },
  { key: 'settings', label: '速率设置' },
]
const comps = {
  dashboard: DashboardView,
  account: AccountView,
  scan: ScanView,
  candidates: CandidatesView,
  freegames: FreeGamesView,
  workshop: WorkshopView,
  monitor: MonitorView,
  cleaner: CleanerView,
  collections: CollectionsView,
  claim: ClaimView,
  settings: SettingsView,
}
const active = ref(localStorage.getItem('steam_dlc_tab') || 'dashboard')
const version = ref('1.3.0')
const build = ref('')
const session = ref({ configured: false, has_key: false, has_steamid: false, profile_exists: false })
const update = ref({ available: false, latest: '', release_url: '' })
const pro = ref(false)
const showAbout = ref(false)
const REPO_URL = 'https://github.com/zlwzk/steam-toolbox'

const configured = computed(() => !!session.value.configured)
// 未激活完整版时隐藏 pro 导航项；布局按剩余标签自然排布，不留占位空白
const visibleTabs = computed(() => tabs.filter((t) => !t.pro || pro.value))

// 连点版本号激活：3 秒内连续点 5 下触发
const CLICK_WINDOW = 3000
const CLICK_NEED = 5
let clickCount = 0
let clickAt = 0

// 构建号格式 YYYYMMDDNN → 展示为「YYYY-MM-DD #序号」；解析失败时原样返回
function formatBuild(b) {
  const s = String(b || '').trim()
  const m = s.match(/^(\d{4})(\d{2})(\d{2})(\d{2})$/)
  if (!m) return s
  return `${m[1]}-${m[2]}-${m[3]} #${Number(m[4])}`
}

// 标题栏小标签用的短构建号：取年后两位 + 月日 + 序号（如 261112.4）
const buildShort = computed(() => {
  const s = String(build.value || '').trim()
  const m = s.match(/^(\d{4})(\d{2})(\d{2})(\d{2})$/)
  return m ? `${m[1].slice(2)}${m[2]}${m[3]}.${Number(m[4])}` : s
})

function setTab(key) {
  active.value = key
  try { localStorage.setItem('steam_dlc_tab', key) } catch { /* 存储不可用时忽略 */ }
}

async function loadVersion() {
  try {
    const v = await api.version()
    if (v.version) version.value = v.version
    if (v.build) build.value = v.build
  } catch {
    /* 版本接口暂不可达时保留本地兜底值 */
  }
}

async function loadSession() {
  try {
    session.value = await api.sessionStatus()
    if (session.value.version) version.value = session.value.version
    if (session.value.build) build.value = session.value.build
  } catch {
    /* 会话状态拉取失败时保留默认，不阻断界面 */
  }
  // 版本信息再以独立 /api/version 兜底回填，避免会话接口缺构建号时徽章留空
  await loadVersion()
}

async function loadUpdate() {
  try {
    update.value = await api.updateCheck()
  } catch {
    /* 网络不可达时按无更新处理 */
  }
}

async function loadPro() {
  try {
    const r = await api.proStatus()
    pro.value = !!r.unlocked
  } catch {
    pro.value = false
  }
  // 本地记忆的标签若属于未激活的完整版项，回退到总览，避免进入空白组件
  if (!pro.value && tabs.some((t) => t.pro && t.key === active.value)) {
    setTab('dashboard')
  }
}

async function handleBadgeClick() {
  if (pro.value) {
    showAbout.value = true
    return
  }
  const now = Date.now()
  if (now - clickAt > CLICK_WINDOW) {
    clickCount = 0
    clickAt = now
  }
  clickCount += 1
  if (clickCount >= CLICK_NEED) {
    clickCount = 0
    try {
      const r = await api.proUnlock()
      pro.value = !!r.unlocked
      if (pro.value) showAbout.value = true
    } catch {
      /* 解锁请求失败时保持未激活 */
    }
  }
}

async function recheck() {
  await loadUpdate()
}

onMounted(() => {
  loadSession()
  loadPro()
  loadUpdate()
})
</script>

<template>
  <header>
    <h1>
      Steam 工具助手
      <span
        class="ver-badge"
        :title="`版本 v${version}${build ? ' · 构建 ' + build + '（' + formatBuild(build) + '）' : ''}，点击查看关于`"
        @click="handleBadgeClick"
      >
        <span class="ver-num">v{{ version }}</span>
        <span v-if="build" class="build-tag">b{{ buildShort }}</span>
      </span>
    </h1>
    <nav>
      <button
        v-for="t in visibleTabs"
        :key="t.key"
        :class="{ active: active === t.key, pending: t.key === 'account' && !configured }"
        @click="setTab(t.key)"
      >
        {{ t.label }}
        <span v-if="t.key === 'account' && !configured" class="nav-dot" title="尚未完成账号绑定"></span>
      </button>
    </nav>
    <div class="header-right">
      <a
        v-if="update.available"
        class="update-link"
        :href="update.release_url"
        target="_blank"
        rel="noopener noreferrer"
      >发现新版本 v{{ update.latest }} ↗</a>
    </div>
  </header>
  <main>
    <div v-if="!configured" class="guide-bar">
      <div class="guide-title">首次使用：先完成账号绑定</div>
      <ol class="guide-steps">
        <li>填写你的 <b>17 位 SteamID</b>（7656119 开头）。</li>
        <li>申请并粘贴 <b>Steam Web API Key</b>（仅保存在本机数据库，不上传）。</li>
        <li>在弹出的浏览器中登录一次 Steam，登录态会留在本机 Profile，之后无需重复登录。</li>
      </ol>
      <button class="primary" @click="setTab('account')">前往账号绑定 →</button>
    </div>
    <component :is="comps[active]" @navigate="setTab" @session-refresh="loadSession" />
    <LogPanel />
  </main>

  <div v-if="showAbout" class="modal-mask" @click.self="showAbout = false">
    <div class="modal">
      <h3 style="margin:0 0 12px;">关于 Steam 工具助手</h3>
      <div class="about-version">
        <div class="about-ver-main">v{{ version }}</div>
        <div class="about-ver-sub">内部构建 {{ build || '—' }}<span v-if="build">（{{ formatBuild(build) }}）</span></div>
      </div>
      <p class="muted" style="margin:8px 0;">
        当前版本 v{{ version }}<span v-if="update.latest"> · 最新版本 v{{ update.latest }}</span>
      </p>
      <p v-if="update.available" class="msg msg-ok" style="margin:8px 0;">
        发现新版本 v{{ update.latest }}，
        <a class="inline-link" :href="update.release_url" target="_blank" rel="noopener noreferrer" style="margin-left:0;">前往下载 ↗</a>
      </p>
      <p v-else-if="update.latest" class="muted">已是当前最新版本。</p>
      <p v-else class="muted">未检测到远程版本（网络不可达），不影响本地使用。</p>
      <p class="muted">完整版状态：{{ pro ? '已激活' : '未激活' }}</p>
      <p>
        <a class="inline-link" :href="REPO_URL" target="_blank" rel="noopener noreferrer" style="margin-left:0;">开源仓库 ↗</a>
      </p>
      <div class="row">
        <button class="ghost" @click="recheck">重新检查更新</button>
        <button class="primary" @click="showAbout = false">关闭</button>
      </div>
    </div>
  </div>
</template>
