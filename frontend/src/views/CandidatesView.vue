<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const tabs = [
  { key: '', label: '全部' },
  { key: 'claimable', label: '可领' },
  { key: 'owned', label: '已拥有' },
  { key: 'skipped', label: '跳过' },
  { key: 'unknown', label: '待确认' },
]
const status = ref('')
const favoriteOnly = ref(false)
const showIgnored = ref(false)
const langFilter = ref('')
const list = ref([])
const sum = ref({ claimable: 0, owned: 0, skipped: 0, unknown: 0, total: 0 })
const emit = defineEmits(['navigate'])
const selected = ref({})
const { msg, ok, err, errText } = useMsg()
const claiming = ref(false)
const scanProg = ref({ state: 'idle', kind: 'dlc' })
let timer = null

const checkedList = computed(() => list.value.filter((r) => selected.value[r.dlc_appid]))
const claimableVisible = computed(() => list.value.filter((r) => r.status === 'claimable'))
const allChecked = computed(
  () => claimableVisible.value.length > 0 && claimableVisible.value.every((r) => selected.value[r.dlc_appid])
)

function toggleAll() {
  if (allChecked.value) {
    selected.value = {}
  } else {
    const next = { ...selected.value }
    claimableVisible.value.forEach((r) => { next[r.dlc_appid] = true })
    selected.value = next
  }
}

function params() {
  return {
    status: status.value,
    item_type: 'dlc',
    favorite: favoriteOnly.value ? '1' : '',
    ignored: showIgnored.value ? '1' : '',
    lang: langFilter.value,
  }
}

async function load() {
  try {
    list.value = await api.candidates(params())
    sum.value = await api.summary('dlc')
    selected.value = {}
  } catch (e) {
    err('加载 DLC 清单失败：' + errText(e))
  }
}

async function refreshScan() {
  try {
    const prev = scanProg.value.state
    scanProg.value = await api.progress()
    const done = scanProg.value.kind === 'dlc' &&
      (scanProg.value.state === 'done' || scanProg.value.state === 'error')
    if (done && prev !== scanProg.value.state) load()
  } catch {
    /* 轮询失败静默 */
  }
}

function toggle(row) {
  if (row.status !== 'claimable') return
  selected.value[row.dlc_appid] = !selected.value[row.dlc_appid]
}

async function mark(row, field) {
  const value = field === 'favorite' ? !row.favorite : !row.ignored
  try {
    await api.markCandidate(row.dlc_appid, field, value)
    row[field] = value ? 1 : 0
  } catch (e) {
    err('标记失败：' + errText(e))
  }
}

async function claim() {
  claiming.value = true
  try {
    const items = checkedList.value.map((r) => ({ appid: r.dlc_appid, kind: 'dlc', name: r.name }))
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
  window.open(api.exportUrl('candidates', params()))
}

onMounted(() => {
  load()
  refreshScan()
  timer = setInterval(refreshScan, 2000)
})
onUnmounted(() => clearInterval(timer))
watch([status, favoriteOnly, showIgnored, langFilter], load)

function priceText(row) {
  if (row.price_final == null) return '—'
  return row.price_final === 0 ? '免费' : `${row.currency || ''} ${row.price_final}`
}
</script>

<template>
  <div class="card">
    <div class="stats">
      <div class="stat">总计<b>{{ sum.total }}</b></div>
      <div class="stat">可领<b>{{ sum.claimable }}</b></div>
      <div class="stat">已拥有<b>{{ sum.owned }}</b></div>
      <div class="stat">跳过<b>{{ sum.skipped }}</b></div>
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

    <div class="row" style="margin-bottom:12px;gap:12px;flex-wrap:wrap;align-items:center;">
      <label><input type="checkbox" v-model="favoriteOnly" /> 仅收藏</label>
      <label><input type="checkbox" v-model="showIgnored" /> 显示已忽略</label>
      <input v-model="langFilter" placeholder="语言过滤，如 简体中文" style="padding:6px;" />
      <button class="primary" :disabled="!checkedList.length || claiming" @click="claim">
        {{ claiming ? '提交中…' : `领取选中（${checkedList.length}）` }}
      </button>
      <button @click="exportCsv">导出 CSV</button>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <table>
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              :checked="allChecked"
              :disabled="!claimableVisible.length"
              @change="toggleAll"
              title="全选当前可领条目"
            />
          </th>
          <th>封面</th>
          <th>DLC 名称</th>
          <th>所属本体</th>
          <th>类型</th>
          <th>价格</th>
          <th>状态</th>
          <th>原因</th>
          <th>标记</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in list" :key="row.dlc_appid" :class="{ ignored: row.ignored }">
          <td>
            <input
              type="checkbox"
              :checked="!!selected[row.dlc_appid]"
              :disabled="row.status !== 'claimable'"
              @change="toggle(row)"
            />
          </td>
          <td>
            <img v-if="row.cover_url" :src="row.cover_url" class="cover-sm" alt="" />
            <span v-else class="muted">—</span>
          </td>
          <td>{{ row.name || `#${row.dlc_appid}` }}</td>
          <td class="muted">{{ row.parent_name || `#${row.parent_appid}` }}</td>
          <td class="muted">{{ row.type }}</td>
          <td>{{ priceText(row) }}</td>
          <td><span class="badge" :class="row.status">{{ row.status }}</span></td>
          <td class="muted">{{ row.reason }}</td>
          <td class="mark-cell">
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
          </td>
        </tr>
        <tr v-if="!list.length">
          <td colspan="9" class="muted" style="text-align:center;padding:30px;">暂无数据，请先在「DLC 扫描」中开始扫描</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
