<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const tabs = [
  { key: '', label: '全部' },
  { key: 'limited_free', label: '喜加一' },
  { key: 'permanent_free', label: '永久免费' },
  { key: 'paid', label: '付费' },
  { key: 'demo', label: 'Demo' },
  { key: 'owned', label: '已拥有' },
  { key: 'unknown', label: '待确认' },
]
const status = ref('')
const favoriteOnly = ref(false)
const showIgnored = ref(false)
const langFilter = ref('')
const list = ref([])
const sum = ref({ limited_free: 0, permanent_free: 0, paid: 0, demo: 0, unknown: 0, total: 0 })
const progress = ref({ state: 'idle', kind: 'freegame', total: 0, current: 0, message: '', counts: {} })
const emit = defineEmits(['navigate'])
const selected = ref({})
const { msg, ok, err, errText } = useMsg()
const claiming = ref(false)
let timer = null

const running = computed(() => progress.value.state === 'running' && progress.value.kind === 'freegame')
const paused = computed(() => progress.value.state === 'paused' && progress.value.kind === 'freegame')
const busy = computed(() => running.value || paused.value)
const pct = computed(() => (progress.value.total ? Math.round((progress.value.current / progress.value.total) * 100) : 0))
const checkedList = computed(() => list.value.filter((r) => selected.value[r.appid]))
const claimableVisible = computed(() => list.value.filter((r) => r.status === 'limited_free'))
const allChecked = computed(
  () => claimableVisible.value.length > 0 && claimableVisible.value.every((r) => selected.value[r.appid])
)

function toggleAll() {
  if (allChecked.value) {
    selected.value = {}
  } else {
    const next = { ...selected.value }
    claimableVisible.value.forEach((r) => { next[r.appid] = true })
    selected.value = next
  }
}

function params() {
  return {
    status: status.value,
    favorite: favoriteOnly.value ? '1' : '',
    ignored: showIgnored.value ? '1' : '',
    lang: langFilter.value,
  }
}

async function load() {
  try {
    list.value = await api.freegames(params())
    sum.value = await api.freeSummary()
    selected.value = {}
  } catch (e) {
    err('加载喜加一列表失败：' + errText(e))
  }
}

async function refreshProgress() {
  try {
    progress.value = await api.progress()
    if (progress.value.state === 'done' || progress.value.state === 'error') {
      load()
    }
  } catch {
    /* 轮询失败静默，等待下一次 */
  }
}

async function start() {
  try {
    await api.startScan('freegame')
    refreshProgress()
  } catch (e) {
    err('启动扫描失败：' + errText(e))
  }
}

async function pause() {
  try {
    await api.pauseScan()
    refreshProgress()
  } catch (e) {
    err('暂停失败：' + errText(e))
  }
}

async function resume() {
  try {
    await api.resumeScan()
    refreshProgress()
  } catch (e) {
    err('继续失败：' + errText(e))
  }
}

function toggle(row) {
  if (row.status !== 'limited_free') return
  selected.value[row.appid] = !selected.value[row.appid]
}

async function mark(row, field) {
  const value = field === 'favorite' ? !row.favorite : !row.ignored
  try {
    await api.markFreegame(row.appid, field, value)
    row[field] = value ? 1 : 0
  } catch (e) {
    err('标记失败：' + errText(e))
  }
}

async function claim() {
  claiming.value = true
  try {
    const items = checkedList.value.map((r) => ({ appid: r.appid, kind: 'game', name: r.name }))
    const r = await api.startClaim(items)
    if (r.ok) {
      ok(`已提交 ${r.count} 个领取任务，请到「领取记录」查看进度`)
      emit('navigate', 'claim')
    } else err(`提交失败：${r.error || '未知原因'}`)
  } catch (e) {
    err('提交领取失败：' + errText(e))
  } finally {
    claiming.value = false
  }
}

function exportCsv() {
  window.open(api.exportUrl('freegames', params()))
}

onMounted(() => {
  load()
  refreshProgress()
  timer = setInterval(refreshProgress, 2000)
})
onUnmounted(() => clearInterval(timer))
watch([status, favoriteOnly, showIgnored, langFilter], load)

function badgeClass(s) {
  return { limited_free: 'claimable', permanent_free: 'owned', owned: 'owned', paid: 'skipped', demo: 'skipped', unknown: 'unknown' }[s] || 'skipped'
}

function priceText(row) {
  if (row.status === 'limited_free') return `原价 ${row.currency || ''} ${row.price_initial} → 限时免费`
  if (row.status === 'permanent_free') return '永久免费（不领取）'
  if (row.status === 'demo') return '试玩 Demo'
  if (row.price_final != null) return `${row.currency || ''} ${row.price_final}`
  return '—'
}
</script>

<template>
  <div class="card">
    <div class="row" style="align-items:center; gap:16px; flex-wrap:wrap;">
      <button v-if="running" class="primary" @click="pause">暂停</button>
      <button v-else-if="paused" class="primary" @click="resume">继续</button>
      <button v-else class="primary" @click="start">扫描喜加一</button>
      <label v-if="claimableVisible.length">
        <input type="checkbox" :checked="allChecked" @change="toggleAll" /> 全选可领
      </label>
      <button class="ghost" :disabled="!checkedList.length || claiming" @click="claim">
        {{ claiming ? '提交中…' : `领取选中（${checkedList.length}）` }}
      </button>
      <button @click="exportCsv">导出 CSV</button>
      <label><input type="checkbox" v-model="favoriteOnly" /> 仅收藏</label>
      <label><input type="checkbox" v-model="showIgnored" /> 显示已忽略</label>
      <input v-model="langFilter" placeholder="语言过滤，如 简体中文" style="padding:6px;" />
      <span class="muted">{{ progress.message }}</span>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <div class="progress" v-if="busy" style="margin:16px 0;">
      <span :style="{ width: pct + '%' }"></span>
    </div>
    <div class="muted" v-if="busy" style="display:flex; gap:16px; flex-wrap:wrap;">
      <span>阶段：{{ progress.stage || '—' }}</span>
      <span>进度：{{ progress.current }} / {{ progress.total }}（{{ pct }}%）</span>
      <span v-if="progress.cached">缓存命中 {{ progress.cached }}</span>
    </div>

    <div class="stats" style="margin-top:16px;">
      <div class="stat">喜加一<b>{{ sum.limited_free }}</b></div>
      <div class="stat">永久免费<b>{{ sum.permanent_free }}</b></div>
      <div class="stat">付费<b>{{ sum.paid }}</b></div>
      <div class="stat">Demo<b>{{ sum.demo }}</b></div>
      <div class="stat">待确认<b>{{ sum.unknown }}</b></div>
    </div>

    <div class="tabs">
      <button
        v-for="t in tabs"
        :key="t.key"
        :class="{ active: status === t.key }"
        @click="status = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <div v-if="list.length" class="game-grid">
      <div v-for="row in list" :key="row.appid" class="game-card" :class="{ ignored: row.ignored }">
        <label class="cover-check">
          <input
            type="checkbox"
            :checked="!!selected[row.appid]"
            :disabled="row.status !== 'limited_free'"
            @change="toggle(row)"
          />
        </label>
        <img :src="row.cover_url" class="cover-md" alt="" />
        <div class="game-info">
          <div class="game-name">{{ row.name || `#${row.appid}` }}</div>
          <div class="muted">{{ priceText(row) }}</div>
          <div style="margin:6px 0;">
            <span class="badge" :class="badgeClass(row.status)">{{ row.status }}</span>
          </div>
          <div class="muted desc">{{ row.description || row.reason }}</div>
          <div class="mark-cell" style="margin-top:6px;">
            <button
              :title="row.favorite ? '取消收藏' : '收藏'"
              :class="['icon-btn', { on: row.favorite }]"
              @click="mark(row, 'favorite')"
            >★</button>
            <button
              :title="row.ignored ? '取消忽略' : '忽略'"
              :class="['icon-btn', { on: row.ignored }]"
              @click="mark(row, 'ignored')"
            >🚫</button>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="muted" style="text-align:center;padding:30px;">
      暂无数据，点击「扫描喜加一」抓取商店限时免费游戏
    </div>
  </div>
</template>
