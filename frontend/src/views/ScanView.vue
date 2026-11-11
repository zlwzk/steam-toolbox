<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const emit = defineEmits(['navigate'])

const p = ref({ state: 'idle', kind: 'dlc', stage: '', total: 0, current: 0, cached: 0, message: '', counts: {}, interrupted: false, resumable: false, interrupted_kind: 'dlc' })
const ov = ref({ owned: 0, dlc_total: 0, dlc_claimable: 0, free_total: 0, free_limited: 0, last_scan_at: null })
const account = ref({ has_key: false, has_steamid: false })
const { msg, err, errText } = useMsg()
let timer = null

const running = computed(() => p.value.state === 'running')
const paused = computed(() => p.value.state === 'paused')
const busy = computed(() => running.value || paused.value)
const pct = computed(() => (p.value.total ? Math.round((p.value.current / p.value.total) * 100) : 0))
const accountReady = computed(() => !!account.value.has_key && !!account.value.has_steamid)

async function refresh() {
  try {
    p.value = await api.progress()
    ov.value = await api.overview()
  } catch {
    /* 轮询失败静默，等待下一次 */
  }
}

async function loadAccount() {
  try {
    account.value = await api.getAccount()
  } catch {
    /* 忽略，按未配置处理 */
  }
}

async function start(kind = 'dlc', force = false) {
  if (!accountReady.value) {
    err('请先在「账号绑定」页填写 API Key 与 SteamID')
    emit('navigate', 'account')
    return
  }
  try {
    await api.startScan(kind, force)
    refresh()
  } catch (e) {
    err('启动扫描失败：' + errText(e))
  }
}

async function pause() {
  try {
    await api.pauseScan()
    refresh()
  } catch (e) {
    err('暂停失败：' + errText(e))
  }
}

async function resume() {
  try {
    await api.resumeScan()
    refresh()
  } catch (e) {
    err('继续失败：' + errText(e))
  }
}

async function continueLast() {
  start(p.value.interrupted_kind || 'dlc', false)
}

onMounted(() => {
  loadAccount()
  refresh()
  timer = setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="card">
    <h2>扫描盘点</h2>
    <p class="muted">读取库内本体及其 DLC，按规则判定是否免费可领。默认增量扫描：详情命中本地缓存不会重复请求；盘点阶段只发 GET 请求，按设置的随机间隔限速。</p>

    <div v-if="!accountReady" class="msg msg-err" style="margin-bottom:12px;">
      尚未配置 API Key 或 SteamID，请先到「账号绑定」完成绑定后再扫描。
      <button class="ghost" style="margin-left:8px;" @click="emit('navigate','account')">去绑定</button>
    </div>

    <div class="stats" style="margin-bottom:16px;">
      <div class="stat">库内本体<b>{{ ov.owned }}</b></div>
      <div class="stat">DLC 总计<b>{{ ov.dlc_total }}</b></div>
      <div class="stat">可领 DLC<b>{{ ov.dlc_claimable }}</b></div>
      <div class="stat">喜加一<b>{{ ov.free_limited }}</b></div>
      <div class="stat">上次扫描<b>{{ ov.last_scan_at || '—' }}</b></div>
    </div>

    <div class="row" style="align-items:center; gap:12px; flex-wrap:wrap;">
      <button v-if="running" class="primary" @click="pause">暂停</button>
      <button v-else-if="paused" class="primary" @click="resume">继续</button>
      <button v-else-if="p.resumable" class="primary" :disabled="!accountReady" @click="continueLast">
        继续上次扫描（走缓存）
      </button>
      <button v-else class="primary" :disabled="!accountReady" @click="start('dlc', false)">
        刷新扫描（走缓存）
      </button>
      <button class="ghost" :disabled="busy || !accountReady" @click="start('dlc', true)">
        强制全量重扫
      </button>
      <span class="muted">{{ p.message }}</span>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <div v-if="busy" class="muted" style="margin:8px 0 0;">
      上次未完成的盘点会保留在本机，继续时优先走本地缓存，不会从头重复请求。
    </div>

    <div class="progress" v-if="busy" style="margin:16px 0;">
      <span :style="{ width: pct + '%' }"></span>
    </div>
    <div class="muted" style="display:flex; gap:16px; flex-wrap:wrap;">
      <span>阶段：{{ p.stage || '—' }}</span>
      <span>进度：{{ p.current }} / {{ p.total }}（{{ pct }}%）</span>
      <span v-if="p.cached">缓存命中 {{ p.cached }}</span>
    </div>

    <div class="stats" style="margin-top:16px;">
      <div class="stat">可领<b>{{ p.counts.claimable || 0 }}</b></div>
      <div class="stat">已拥有<b>{{ p.counts.owned || 0 }}</b></div>
      <div class="stat">跳过<b>{{ p.counts.skipped || 0 }}</b></div>
      <div class="stat">待确认<b>{{ p.counts.unknown || 0 }}</b></div>
    </div>
  </div>
</template>
