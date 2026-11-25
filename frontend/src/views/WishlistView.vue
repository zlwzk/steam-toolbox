<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'
import CdkPanel from './CdkPanel.vue'

// 两个子功能：① 游戏入库登记（名称/AppID → 解析 → 中英文补全 → 登记）
//           ② CDK 登记（仅本地登记 + 人工激活辅助；工具不自动提交激活）
const tab = ref('wishlist')

const inputText = ref('')
const resolving = ref(false)
const results = ref([])
const indexStale = ref(false)
const savedList = ref([])
const selected = ref({})
const saving = ref(false)
const { msg, ok, err, errText } = useMsg()

const lines = computed(() => inputText.value.split('\n').map((l) => l.trim()).filter(Boolean))
const exactCount = computed(() => results.value.filter((r) => r.resolve_status === 'exact').length)
const unresolvedCount = computed(() => results.value.filter((r) => r.resolve_status === 'unresolved').length)

const STATUS_LABEL = {
  exact: '已确认',
  appid_only: 'ID 确认·名称未知',
  unresolved: '未能确认',
  invalid: '无效输入',
}

function displayName(r) {
  return r.name_zh || r.name_en || r.raw_name || '（名称未知）'
}

async function doResolve() {
  if (!lines.value.length) { err('请先填写游戏名称或 AppID（每行一条）'); return }
  resolving.value = true
  results.value = []
  try {
    const r = await api.wlResolve({ inputs: lines.value })
    results.value = r.results || []
    indexStale.value = !!r.index_stale
    if (results.value.length) ok(`解析完成：${exactCount.value} 条已确认，${unresolvedCount.value} 条未能确认；保存时会重新核验`)
    else err('没有可解析的条目')
  } catch (e) {
    err('解析失败：' + errText(e))
  } finally {
    resolving.value = false
  }
}

async function doSave() {
  // 二次确认：明确告知 unresolved 条目也会登记（保留原因），不伪称全部确认
  const n = lines.value.length
  const unres = unresolvedCount.value
  const tip = unres > 0
    ? `将重新核验并登记最多 ${n} 条；预览中 ${unres} 条未能唯一确认。结果可能变化，未确认项会保留原因，之后可删除并以 AppID 重新登记。继续？`
    : `将重新核验并登记最多 ${n} 条到本机清单（不是 Steam 账号）。继续？`
  if (!window.confirm(tip)) return
  saving.value = true
  try {
    const r = await api.wlSave({ inputs: lines.value })
    if (r.ok) {
      ok(`已登记 ${r.saved} 条（确认 ${r.exact}，未确认 ${r.unresolved}）`)
      inputText.value = ''
      results.value = []
      loadList()
    } else err(r.error || '登记失败')
  } catch (e) {
    err('登记失败：' + errText(e))
  } finally {
    saving.value = false
  }
}

async function loadList() {
  try { savedList.value = await api.wlList() } catch { /* 静默，下次重试 */ }
}

async function removeItem(row) {
  if (!window.confirm(`从登记清单移除「${row.name_zh || row.name_en || row.input_text}」？`)) return
  try {
    await api.wlRemove(row.input_text)
    loadList()
  } catch (e) { err(errText(e)) }
}

async function clearAll() {
  if (!savedList.value.length) return
  if (!window.confirm(`确定清空全部 ${savedList.value.length} 条登记？不会影响 Steam 账号。`)) return
  try { await api.wlClear(); loadList(); ok('已清空登记清单') } catch (e) { err(errText(e)) }
}

onMounted(loadList)
</script>

<template>
  <div class="card">
    <div class="tabs" style="margin-bottom:16px;">
      <button :class="{ active: tab === 'wishlist' }" @click="tab = 'wishlist'">游戏入库登记</button>
      <button :class="{ active: tab === 'cdk' }" @click="tab = 'cdk'">CDK 激活码登记</button>
    </div>

    <!-- ===================== 游戏入库登记 ===================== -->
    <template v-if="tab === 'wishlist'">
      <h2>游戏入库登记</h2>
      <p class="muted">
        每行一条，支持<b>游戏名称（中英文均可）或 AppID</b>。工具通过 Steam 官方目录与商店接口匹配，
        并补全中英文官方名称。这里的「入库」仅指保存到本机待处理清单，<b>不会将游戏加入 Steam 账号</b>；
        无法唯一确认的条目保留原输入和候选，不猜测拥有、价格或领取结果。
      </p>

      <div class="field">
        <label>批量输入（名称 / AppID，每行一条，单次最多 50 条）</label>
        <textarea v-model="inputText" rows="6" placeholder="示例：&#10;Terraria&#10;泰拉瑞亚&#10;105600&#10;Counter-Strike 2"></textarea>
      </div>

      <div class="row" style="gap:12px; margin-top:12px;">
        <button class="primary" :disabled="resolving || !lines.length" @click="doResolve">
          {{ resolving ? '正在解析…' : '解析预览' }}
        </button>
        <button :disabled="saving || !lines.length" @click="doSave">直接登记</button>
        <span class="muted">先预览可核对匹配结果，或直接登记（内部同样先解析）</span>
      </div>
      <p class="muted" v-if="indexStale" style="margin-top:6px;">
        注意：官方游戏目录索引刷新失败，当前使用旧缓存或仅商店搜索，个别名称可能无法确认。
      </p>

      <div v-if="results.length" style="margin-top:16px;">
        <h3>解析预览（{{ results.length }} 条）</h3>
        <table>
          <thead>
            <tr><th>输入</th><th>AppID</th><th>中文名</th><th>英文名</th><th>状态</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in results" :key="i">
              <td>{{ r.input }}</td>
              <td>{{ r.appid ?? '—' }}</td>
              <td>{{ r.name_zh ?? '未知' }}</td>
              <td>{{ r.name_en ?? '未知' }}</td>
              <td><span class="badge" :class="r.resolve_status === 'exact' ? 'success' : 'muted'">{{ STATUS_LABEL[r.resolve_status] || r.resolve_status }}</span></td>
              <td class="muted">{{ r.reason || (r.resolve_status === 'exact' ? displayName(r) : '') }}<span v-if="r.candidates?.length">；候选：{{ r.candidates.map((c) => `${c.name || '名称未知'} (AppID ${c.appid})`).join('、') }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style="margin-top:24px;">
        <div class="row" style="justify-content:space-between;">
          <h3 style="margin:0;">已登记清单（{{ savedList.length }}）</h3>
          <button v-if="savedList.length" class="ghost" @click="clearAll">清空清单</button>
        </div>
        <table v-if="savedList.length" style="margin-top:8px;">
          <thead>
            <tr><th>AppID</th><th>输入</th><th>中文名</th><th>英文名</th><th>状态</th><th>登记时间</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="row in savedList" :key="row.input_text">
              <td>{{ row.appid }}</td>
              <td>{{ row.input_text }}</td>
              <td>{{ row.name_zh ?? '未知' }}</td>
              <td>{{ row.name_en ?? '未知' }}</td>
              <td><span class="badge" :class="row.resolve_status === 'exact' ? 'success' : 'muted'">{{ STATUS_LABEL[row.resolve_status] || row.resolve_status }}</span></td>
              <td class="muted">{{ row.added_at }}</td>
              <td><button class="ghost" @click="removeItem(row)">移除</button></td>
            </tr>
          </tbody>
        </table>
        <p class="muted" v-else style="text-align:center;padding:24px;">暂无登记；上方输入后点击「直接登记」</p>
      </div>
    </template>

    <!-- ===================== CDK 登记 ===================== -->
    <template v-else>
      <CdkPanel />
    </template>
  </div>
</template>
