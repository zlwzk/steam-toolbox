<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const appid = ref('')
const mode = ref('subscribe')
const auto = ref(true)
const rangeStart = ref(0)
const rangeEnd = ref(0)
const list = ref([])
const statusFilter = ref('')
const progress = ref({ state: 'idle', total: 0, current: 0, message: '', counts: {}, paused: false })
const selected = ref({})
const { msg, ok, err, errText } = useMsg()
let timer = null

const running = computed(() => ['running', 'paused'].includes(progress.value.state))
const pct = computed(() => progress.value.total ? Math.round((progress.value.current / progress.value.total) * 100) : 0)
const failedCount = computed(() => list.value.filter((r) => r.status === 'failed').length)

const tabs = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待处理' },
  { key: 'success', label: '成功' },
  { key: 'failed', label: '失败' },
]

async function load() {
  try {
    list.value = await api.wsItems(statusFilter.value)
  } catch (e) {
    err('加载工坊列表失败：' + errText(e))
  }
}

async function refreshProgress() {
  try {
    progress.value = await api.wsProgress()
    if (['done', 'blocked', 'error'].includes(progress.value.state)) load()
  } catch { /* 静默 */ }
}

async function start() {
  try {
    const r = await api.wsStart({
      appid: appid.value.trim(),
      mode: mode.value,
      auto: auto.value,
      range_start: Number(rangeStart.value) || 0,
      range_end: Number(rangeEnd.value) || 0,
    })
    if (r.ok) {
      ok('工坊任务已启动')
      refreshProgress()
    } else err(`启动失败：${r.error || '未知原因'}`)
  } catch (e) {
    err('启动失败：' + errText(e))
  }
}

async function pause() {
  try { await api.wsPause(); refreshProgress() } catch (e) { err('操作失败：' + errText(e)) }
}

async function cancel() {
  try { await api.wsCancel(); refreshProgress() } catch (e) { err('取消失败：' + errText(e)) }
}

async function retryFailed() {
  try {
    const r = await api.wsRetry()
    if (r.ok) ok(`已重试 ${r.count} 个失败项`)
    else err(r.error || '无失败项')
  } catch (e) { err('重试失败：' + errText(e)) }
}

async function mark(row, field) {
  const value = field === 'favorite' ? !row.favorite : !row.ignored
  try {
    await api.wsMark(row.published_file_id, field, value)
    row[field] = value ? 1 : 0
  } catch (e) { err('标记失败：' + errText(e)) }
}

async function clearAll() {
  if (!confirm('确定清空本地工坊记录？不会影响 Steam 上的订阅状态。')) return
  try { await api.wsClear(); load(); ok('已清空本地记录') } catch (e) { err(errText(e)) }
}

function exportCsv() { window.open('/api/workshop/export.csv') }

onMounted(() => { load(); refreshProgress(); timer = setInterval(refreshProgress, 2000) })
onUnmounted(() => clearInterval(timer))

function badgeClass(s) {
  return { success: 'claimable', failed: 'unknown', pending: 'owned' }[s] || 'skipped'
}
</script>

<template>
  <div class="card">
    <div class="row" style="align-items:center; gap:16px; flex-wrap:wrap;">
      <div class="field" style="margin:0;">
        <label>游戏 AppID</label>
        <input v-model="appid" placeholder="如 730" style="width:120px;" />
      </div>
      <div class="field" style="margin:0;">
        <label>动作</label>
        <select v-model="mode">
          <option value="subscribe">批量订阅</option>
          <option value="unsubscribe">批量退订</option>
        </select>
      </div>
      <label><input type="checkbox" v-model="auto" /> 自动翻页（处理全部页）</label>
      <div class="field" style="margin:0;">
        <label>序号范围（起始）</label>
        <input v-model.number="rangeStart" type="number" min="0" style="width:90px;" />
      </div>
      <div class="field" style="margin:0;">
        <label>序号范围（结束）</label>
        <input v-model.number="rangeEnd" type="number" min="0" style="width:90px;" />
      </div>
      <button v-if="!running" class="primary" @click="start">开始</button>
      <button v-else class="primary" @click="pause">{{ progress.paused ? '继续' : '暂停' }}</button>
      <button v-if="running" class="ghost" @click="cancel">取消</button>
      <button class="ghost" :disabled="!failedCount" @click="retryFailed">重试失败（{{ failedCount }}）</button>
      <button @click="exportCsv">导出 CSV</button>
      <button class="ghost" @click="clearAll">清空记录</button>
      <span class="muted">{{ progress.message }}</span>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <div class="progress" v-if="running" style="margin:16px 0;">
      <span :style="{ width: pct + '%' }"></span>
    </div>
    <div class="muted" v-if="running" style="display:flex; gap:16px; flex-wrap:wrap;">
      <span>进度：{{ progress.current }} / {{ progress.total }}（{{ pct }}%）</span>
      <span v-if="progress.pages_done">已处理 {{ progress.pages_done }} 页</span>
      <span>成功 {{ progress.counts.success || 0 }} · 失败 {{ progress.counts.failed || 0 }}</span>
    </div>

    <div class="tabs">
      <button v-for="t in tabs" :key="t.key" :class="{ active: statusFilter === t.key }" @click="statusFilter = t.key">{{ t.label }}</button>
    </div>

    <div v-if="list.length" class="game-grid">
      <div v-for="row in list" :key="row.published_file_id" class="game-card" :class="{ ignored: row.ignored }">
        <div class="game-info">
          <div class="game-name">{{ row.title || `#${row.published_file_id}` }}</div>
          <div class="muted">文件 ID：{{ row.published_file_id }} · AppID：{{ row.appid }}</div>
          <div style="margin:6px 0;">
            <span class="badge" :class="badgeClass(row.status)">{{ row.status }}</span>
          </div>
          <div class="muted desc">{{ row.reason }}</div>
          <div class="mark-cell" style="margin-top:6px;">
            <button :title="row.favorite ? '取消收藏' : '收藏'" :class="['icon-btn', { on: row.favorite }]" @click="mark(row, 'favorite')">★</button>
            <button :title="row.ignored ? '取消忽略' : '忽略'" :class="['icon-btn', { on: row.ignored }]" @click="mark(row, 'ignored')">🚫</button>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="muted" style="text-align:center;padding:30px;">
      填写游戏 AppID 后点击「开始」，批量订阅当前工坊页 Mod
    </div>
  </div>
</template>
