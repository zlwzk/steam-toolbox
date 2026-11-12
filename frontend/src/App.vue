<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import AccountView from './views/AccountView.vue'
import ScanView from './views/ScanView.vue'
import CandidatesView from './views/CandidatesView.vue'
import FreeGamesView from './views/FreeGamesView.vue'
import WorkshopView from './views/WorkshopView.vue'
import CleanerView from './views/CleanerView.vue'
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
  { key: 'cleaner', label: '库清理' },
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
  cleaner: CleanerView,
  claim: ClaimView,
  settings: SettingsView,
}
const active = ref(localStorage.getItem('steam_dlc_tab') || 'dashboard')
const version = ref('1.2.3')
const build = ref('')
const session = ref({ configured: false, has_key: false, has_steamid: false, profile_exists: false })
const update = ref({ available: false, latest: '', release_url: '' })
const showAbout = ref(false)
const REPO_URL = 'https://github.com/zlwzk/steam-toolbox'

const configured = computed(() => !!session.value.configured)

function setTab(key) {
  active.value = key
  try { localStorage.setItem('steam_dlc_tab', key) } catch { /* 存储不可用时忽略 */ }
}

async function loadSession() {
  try {
    session.value = await api.sessionStatus()
    if (session.value.version) version.value = session.value.version
    if (session.value.build) build.value = session.value.build
  } catch {
    /* 会话状态拉取失败时保留默认，不阻断界面 */
  }
}

async function loadUpdate() {
  try {
    update.value = await api.updateCheck()
  } catch {
    /* 网络不可达时按无更新处理 */
  }
}

async function recheck() {
  await loadUpdate()
}

onMounted(() => {
  loadSession()
  loadUpdate()
})
</script>

<template>
  <header>
    <h1>
      Steam 工具助手
      <span class="ver-badge" title="点击查看关于" @click="showAbout = true">v{{ version }}<span v-if="build" class="build-tag">· build {{ build }}</span></span>
    </h1>
    <nav>
      <button
        v-for="t in tabs"
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
      <p class="muted">外部版本：<b>v{{ version }}</b>　内部构建：<b>{{ build || '—' }}</b></p>
      <p v-if="update.available" class="msg msg-ok" style="margin:8px 0;">
        发现新版本 v{{ update.latest }}，
        <a class="inline-link" :href="update.release_url" target="_blank" rel="noopener noreferrer" style="margin-left:0;">前往下载 ↗</a>
      </p>
      <p v-else class="muted">已是当前最新版本。</p>
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
