<script setup>
import { onMounted, ref } from 'vue'
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
const version = ref('1.1.0')

function setTab(key) {
  active.value = key
  try { localStorage.setItem('steam_dlc_tab', key) } catch { /* 存储不可用时忽略 */ }
}

onMounted(async () => {
  try {
    const v = await api.version()
    if (v && v.version) version.value = v.version
  } catch {
    /* 版本号拉取失败时保留本地兜底值 */
  }
})
</script>

<template>
  <header>
    <h1>
      Steam 工具助手
      <span class="ver-badge">v{{ version }}</span>
    </h1>
    <nav>
      <button
        v-for="t in tabs"
        :key="t.key"
        :class="{ active: active === t.key }"
        @click="setTab(t.key)"
      >
        {{ t.label }}
      </button>
    </nav>
  </header>
  <main>
    <component :is="comps[active]" @navigate="setTab" />
    <LogPanel />
  </main>
</template>
