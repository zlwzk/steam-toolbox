<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const timeMode = ref('never')
const threshold = ref('')
const threshold2 = ref('')
const unit = ref('hour')
const delisted = ref('exclude')
const includePaid = ref(false)

const list = ref([])
const statusFilter = ref('candidate')
const progress = ref({ state: 'idle', total: 0, current: 0, message: '', counts: {} })
const selected = ref({})
const { msg, ok, err, errText } = useMsg()
let timer = null

const running = computed(() => progress.value.state === 'running')
const pct = computed(() => progress.value.total ? Math.round((progress.value.current / progress.value.total) * 100) : 0)
const candidateVisible = computed(() => list.value.filter((r) => r.status === 'candidate'))
const checkedList = computed(() => candidateVisible.value.filter((r) => selected.value[r.appid]))
const allChecked = computed(
  () => candidateVisible.value.length > 0 && candidateVisible.value.every((r) => selected.value[r.appid])
)

const tabs = [
  { key: 'candidate', label: '候选清理' },
  { key: 'kept', label: '已保留' },
  { key: 'pending_remove', label: '待移除' },
]

function toggleAll() {
  if (allChecked.value) selected.value = {}
  else {
    const next = { ...selected.value }
    candidateVisible.value.forEach((r) => { next[r.appid] = true })
    selected.value = next
  }
}

async function load() {
  try {
    list.value = await api.clItems(statusFilter.value)
  } catch (e) { err('加载清理清单失败：' + errText(e)) }
}

async function refreshProgress() {
  try {
    progress.value = await api.clProgress()
    if (['done', 'error'].includes(progress.value.state)) load()
  } catch { /* 静默 */ }
}

async function analyze() {
  try {
    const rule = {
      time_mode: timeMode.value,
      threshold: threshold.value === '' ? null : Number(threshold.value),
      threshold2: threshold2.value === '' ? null : Number(threshold2.value),
      unit: unit.value,
      delisted: delisted.value,
      include_paid: includePaid.value,
    }
    const r = await api.clAnalyze(rule)
    if (r.ok) { ok('开始按规则分析库内游戏…'); refreshProgress() }
    else err(r.error || '启动失败')
  } catch (e) { err('启动分析失败：' + errText(e)) }
}

async function mark(row, field) {
  const value = field === 'favorite' ? !row.favorite : !row.ignored
  try {
    await api.clMark(row.appid, field, value)
    row[field] = value ? 1 : 0
  } catch (e) { err('标记失败：' + errText(e)) }
}

async function removeSelected() {
  if (!checkedList.value.length) return
  if (!confirm(`确认将选中的 ${checkedList.value.length} 个游戏登记为待移除？\n（真实移除流程需在登录环境校准，当前仅记录意图，不会立即删除）`)) return
  try {
    const r = await api.clRemove(checkedList.value.map((r) => r.appid))
    if (r.ok) { ok(r.note || '已登记待移除'); load() }
    else err(r.error || '操作失败')
  } catch (e) { err(errText(e)) }
}

async function clearAll() {
  if (!confirm('确定清空本地清理清单？不会改动 Steam 库。')) return
  try { await api.clClear(); load(); ok('已清空本地清单') } catch (e) { err(errText(e)) }
}

function exportCsv() { window.open('/api/cleaner/export.csv') }

onMounted(() => { load(); refreshProgress(); timer = setInterval(refreshProgress, 2000) })
onUnmounted(() => clearInterval(timer))

function fmtTime(min) {
  if (!min) return '从未游玩'
  if (min < 60) return `${min} 分钟`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} 小时 ${m} 分` : `${h} 小时`
}

function badgeClass(s) {
  return { candidate: 'unknown', kept: 'owned', pending_remove: 'skipped' }[s] || 'skipped'
}
</script>

<template>
  <div class="card">
    <div class="row" style="align-items:end; gap:16px; flex-wrap:wrap;">
      <div class="field" style="margin:0;">
        <label>时长条件</label>
        <select v-model="timeMode">
          <option value="never">从未玩过</option>
          <option value="lt">小于</option>
          <option value="gt">大于</option>
          <option value="range">区间</option>
        </select>
      </div>
      <div class="field" v-if="timeMode !== 'never'" style="margin:0;">
        <label>阈值</label>
        <input v-model="threshold" type="number" min="0" placeholder="留空不限" style="width:100px;" />
      </div>
      <div class="field" v-if="timeMode === 'range'" style="margin:0;">
        <label>上限</label>
        <input v-model="threshold2" type="number" min="0" style="width:100px;" />
      </div>
      <div class="field" style="margin:0;">
        <label>单位</label>
        <select v-model="unit">
          <option value="minute">分钟</option>
          <option value="hour">小时</option>
        </select>
      </div>
      <div class="field" style="margin:0;">
        <label>已下架 / 绝版</label>
        <select v-model="delisted">
          <option value="keep">不排除</option>
          <option value="exclude">排除已下架</option>
          <option value="only">仅看已下架</option>
        </select>
      </div>
      <label><input type="checkbox" v-model="includePaid" /> 包含付费购入（默认排除，防误删）</label>
      <button class="primary" :disabled="running" @click="analyze">{{ running ? '分析中…' : '开始分析（干跑预览）' }}</button>
      <button class="ghost" :disabled="!checkedList.length" @click="removeSelected">登记移除（{{ checkedList.length }}）</button>
      <button @click="exportCsv">导出 CSV</button>
      <button class="ghost" @click="clearAll">清空清单</button>
      <span class="muted">{{ progress.message }}</span>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <div class="progress" v-if="running" style="margin:16px 0;">
      <span :style="{ width: pct + '%' }"></span>
    </div>
    <div class="muted" v-if="running" style="display:flex; gap:16px;">
      <span>进度：{{ progress.current }} / {{ progress.total }}（{{ pct }}%）</span>
    </div>

    <div class="tabs">
      <button v-for="t in tabs" :key="t.key" :class="{ active: statusFilter === t.key }" @click="statusFilter = t.key">{{ t.label }}</button>
    </div>

    <label v-if="candidateVisible.length" style="margin-bottom:10px;">
      <input type="checkbox" :checked="allChecked" @change="toggleAll" /> 全选候选（{{ candidateVisible.length }}）
    </label>

    <div v-if="list.length" class="game-grid">
      <div v-for="row in list" :key="row.appid" class="game-card" :class="{ ignored: row.ignored }">
        <label class="cover-check">
          <input type="checkbox" :checked="!!selected[row.appid]" :disabled="row.status !== 'candidate'" @change="selected[row.appid] = !selected[row.appid]" />
        </label>
        <div class="game-info">
          <div class="game-name">{{ row.name || `#${row.appid}` }}</div>
          <div class="muted">时长：{{ fmtTime(row.playtime_forever) }}</div>
          <div class="muted">类型：{{ row.app_type || '—' }}<span v-if="row.delisted"> · 已下架</span></div>
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
      设置筛选条件后点击「开始分析」，先出干跑预览清单，确认无误再登记移除
    </div>
  </div>
</template>
