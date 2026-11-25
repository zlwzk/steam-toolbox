<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

// CDK 登记面板：本地登记 + 人工激活辅助。
// 安全边界：Steam 未提供公开激活 API，本工具不自动提交激活；
// 只做格式校验、状态登记、明文逐条取回复制与官方入口跳转。
// 「已在 Steam 激活成功」由用户手动标记，工具绝不自动写成功。
const inputKeys = ref('')
const note = ref('')
const adding = ref(false)
const listData = ref({ items: [], counts: {}, total: 0 })
const statusFilter = ref('')
const selectedIds = ref({})
const activateInfo = ref({ web_url: '', client_url: '', note: '' })
const { msg, ok, err, errText } = useMsg()

const lines = computed(() => inputKeys.value.split('\n').map((l) => l.trim()).filter(Boolean))
const items = computed(() => listData.value.items || [])
const counts = computed(() => listData.value.counts || {})
const checkedIds = computed(() => items.value.filter((r) => selectedIds.value[r.id]).map((r) => r.id))

const STATUS_LABEL = { pending: '已登记', ready: '待激活', activated: '已激活', invalid: '格式无效', failed: '激活失败' }

async function load() {
  try { listData.value = await api.cdkList(statusFilter.value) } catch { /* 静默 */ }
}

async function addKeys() {
  if (!lines.value.length) { err('请先填写激活码（每行一条）'); return }
  if (!window.confirm(`将登记 ${lines.value.length} 条激活码到本机列表？\n（仅本地登记，不会提交激活）`)) return
  adding.value = true
  try {
    const r = await api.cdkAdd({ keys: lines.value, note: note.value })
    ok(`登记完成：新增 ${r.added}，格式无效 ${r.invalid}，重复 ${r.duplicate}`)
    inputKeys.value = ''
    load()
  } catch (e) {
    err('登记失败：' + errText(e))
  } finally { adding.value = false }
}

async function confirmSelected() {
  if (!checkedIds.value.length) { err('请先勾选要确认的激活码'); return }
  if (!window.confirm(`确认 ${checkedIds.value.length} 条激活码为「待激活」？\n（仅做格式复验与状态标记，不提交激活）`)) return
  try {
    const r = await api.cdkConfirm({ ids: checkedIds.value })
    ok(`已确认 ${r.confirmed} 条（跳过 ${r.skipped} 条）`)
    selectedIds.value = {}
    load()
  } catch (e) { err(errText(e)) }
}

async function copyKey(row) {
  try {
    const r = await api.cdkReveal(row.id)
    if (r.ok) {
      await navigator.clipboard.writeText(r.key)
      ok('已复制激活码明文（来自本地登记），请尽快到 Steam 官方入口激活')
    } else err(r.error || '取回失败')
  } catch (e) { err('复制失败：' + errText(e)) }
}

async function markResult(row, status) {
  const label = status === 'activated' ? '已在 Steam 激活成功' : '激活失败'
  if (!window.confirm(`把这条激活码标记为「${label}」？\n（仅更新本机记录；激活结果以 Steam 客户端为准）`)) return
  try {
    await api.cdkMark({ id: row.id, status })
    load()
  } catch (e) { err(errText(e)) }
}

async function removeKey(row) {
  if (!window.confirm('删除这条激活码登记（本机明文一并删除）？')) return
  try { await api.cdkRemove(row.id); load() } catch (e) { err(errText(e)) }
}

function openActivate() {
  // 优先唤起 Steam 客户端激活页；不支持协议时用户可点网页入口
  window.open(activateInfo.value.client_url || activateInfo.value.web_url, '_blank')
}

onMounted(async () => {
  load()
  try { activateInfo.value = await api.cdkInfo() } catch { /* 信息接口失败不阻断 */ }
})
</script>

<template>
  <div>
    <h2>CDK 激活码登记</h2>
    <p class="muted">
      批量登记 Steam 激活码并跟踪激活状态。<b>本工具不自动提交激活</b>——Steam 未提供公开激活接口，
      请复制激活码到官方入口（客户端或网页）完成激活，再回到这里标记结果。激活码保存在本机数据库；复制时明文进入系统剪贴板，请及时清除。
    </p>

    <div class="field">
      <label>批量输入激活码（每行一条，单次最多 200 条）</label>
      <textarea v-model="inputKeys" rows="5" placeholder="XXXXX-XXXXX-XXXXX-XXXXX-XXXXX&#10;XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"></textarea>
    </div>
    <div class="field">
      <label>备注（可选，如来源 / 日期）</label>
      <input v-model="note" type="text" placeholder="如：某 Bundle 2026-11" />
    </div>
    <div class="row" style="gap:12px; margin-top:8px;">
      <button class="primary" :disabled="adding || !lines.length" @click="addKeys">
        {{ adding ? '正在登记…' : '登记激活码' }}
      </button>
      <button v-if="activateInfo.web_url" @click="openActivate">打开 Steam 激活入口</button>
      <a v-if="activateInfo.web_url" class="inline-link" :href="activateInfo.web_url" target="_blank" style="align-self:center;">网页激活地址</a>
    </div>

    <div class="stats" style="margin-top:20px;">
      <div class="stat">待激活<b>{{ counts.ready || 0 }}</b></div>
      <div class="stat">已激活<b>{{ counts.activated || 0 }}</b></div>
      <div class="stat">失败<b>{{ counts.failed || 0 }}</b></div>
      <div class="stat">无效<b>{{ counts.invalid || 0 }}</b></div>
    </div>

    <div class="row" style="gap:10px; margin-top:16px; align-items:center;">
      <select v-model="statusFilter" @change="load" style="width:auto;">
        <option value="">全部状态</option>
        <option value="pending">已登记</option>
        <option value="ready">待激活</option>
        <option value="activated">已激活</option>
        <option value="failed">激活失败</option>
        <option value="invalid">格式无效</option>
      </select>
      <button :disabled="!checkedIds.length" @click="confirmSelected">确认勾选项（{{ checkedIds.length }}）</button>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>

    <table v-if="items.length" style="margin-top:12px;">
      <thead>
        <tr>
          <th style="width:32px;"></th>
          <th>激活码（掩码）</th>
          <th>状态</th>
          <th>说明</th>
          <th>登记时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in items" :key="row.id">
          <td><input v-model="selectedIds[row.id]" type="checkbox" /></td>
          <td class="mono">{{ row.key_masked }}</td>
          <td><span class="badge">{{ STATUS_LABEL[row.status] || row.status }}</span></td>
          <td class="muted">{{ row.reason || row.note || '—' }}</td>
          <td class="muted">{{ row.added_at }}</td>
          <td>
            <button class="ghost" style="margin-right:4px;" @click="copyKey(row)">复制明文</button>
            <button v-if="row.status !== 'activated'" class="ghost" style="margin-right:4px;" @click="markResult(row, 'activated')">标记已激活</button>
            <button v-if="row.status !== 'failed' && row.status !== 'activated'" class="ghost" style="margin-right:4px;" @click="markResult(row, 'failed')">标记失败</button>
            <button class="ghost" @click="removeKey(row)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="muted" v-else style="text-align:center;padding:24px;">暂无登记</p>
  </div>
</template>
