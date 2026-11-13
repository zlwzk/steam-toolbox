<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const { msg, ok, err, errText } = useMsg()

const progress = ref({ state: 'idle', total: 0, current: 0, message: '', counts: {} })
const games = ref([])
const mods = ref([])
const rules = ref([])
const events = ref([])
const settings = ref({ watch_auto: false, watch_interval_minutes: 360, watch_auto_subscribe: false, watch_workshop_top: 20 })

const gameForm = ref({ appid: '', watch_store: true, watch_workshop: true })
const modForm = ref({ file_id: '', appid: '' })
const ruleForm = ref({ appid: '', keywords: '', match_mode: 'any', auto_subscribe: false, enabled: true, note: '' })
const eventFilter = ref('')
const onlyUnread = ref(false)

let timer = null
const running = computed(() => ['running', 'paused'].includes(progress.value.state))

const KIND_LABEL = {
  game_store_update: '本体更新',
  mod_new: '新 Mod',
  mod_update: 'Mod 更新',
  rule_hit: '规则命中',
  subscribe: '已订阅',
}
const KIND_CLASS = {
  game_store_update: 'unknown',
  mod_new: 'claimable',
  mod_update: 'owned',
  rule_hit: 'unknown',
  subscribe: 'claimable',
}

async function loadAll() {
  await Promise.all([loadGames(), loadMods(), loadRules(), loadEvents(), loadSettings(), refreshProgress()])
}

async function loadGames() {
  try { games.value = await api.monGames() } catch (e) { err('加载关注游戏失败：' + errText(e)) }
}
async function loadMods() {
  try { mods.value = await api.monMods() } catch (e) { err('加载关注 Mod 失败：' + errText(e)) }
}
async function loadRules() {
  try { rules.value = await api.monRules() } catch (e) { err('加载规则失败：' + errText(e)) }
}
async function loadEvents() {
  try { events.value = await api.monEvents({ kind: eventFilter.value, unread: onlyUnread.value }) } catch { /* 静默 */ }
}
async function loadSettings() {
  try { settings.value = await api.monSettings() } catch { /* 静默 */ }
}
async function refreshProgress() {
  try { progress.value = await api.monProgress() } catch { /* 静默 */ }
}

async function addGame() {
  try {
    const r = await api.monAddGame({ appid: gameForm.value.appid.trim(), watch_store: gameForm.value.watch_store, watch_workshop: gameForm.value.watch_workshop })
    if (r.ok) { ok('已加入监控'); gameForm.value.appid = ''; loadGames() }
    else err(r.error || '添加失败')
  } catch (e) { err('添加失败：' + errText(e)) }
}
async function removeGame(row) {
  if (!confirm(`停止监控游戏 #${row.appid}？仅移除本机关注，不影响 Steam 账号。`)) return
  try { await api.monRemoveGame(row.appid); ok('已移除'); loadGames() } catch (e) { err(errText(e)) }
}

async function addMod() {
  try {
    const r = await api.monAddMod({ file_id: modForm.value.file_id.trim(), appid: modForm.value.appid.trim() })
    if (r.ok) { ok('已关注 Mod'); modForm.value.file_id = ''; modForm.value.appid = ''; loadMods() }
    else err(r.error || '添加失败')
  } catch (e) { err('添加失败：' + errText(e)) }
}
async function removeMod(row) {
  if (!confirm(`取消关注 Mod #${row.published_file_id}？`)) return
  try { await api.monRemoveMod(row.published_file_id); ok('已移除'); loadMods() } catch (e) { err(errText(e)) }
}

async function addRule() {
  try {
    const r = await api.monAddRule({
      appid: ruleForm.value.appid.trim(),
      keywords: ruleForm.value.keywords,
      match_mode: ruleForm.value.match_mode,
      auto_subscribe: ruleForm.value.auto_subscribe,
      enabled: ruleForm.value.enabled,
      note: ruleForm.value.note,
    })
    if (r.ok) { ok('规则已保存'); ruleForm.value = { appid: '', keywords: '', match_mode: 'any', auto_subscribe: false, enabled: true, note: '' }; loadRules() }
    else err(r.error || '保存失败')
  } catch (e) { err('保存失败：' + errText(e)) }
}
async function removeRule(row) {
  if (!confirm('删除这条关键字规则？')) return
  try { await api.monRemoveRule(row.id); ok('已删除'); loadRules() } catch (e) { err(errText(e)) }
}

async function checkNow() {
  try {
    const r = await api.monCheck()
    if (r.ok) ok('已开始检测')
    else err(r.error || '无法开始检测')
    refreshProgress()
  } catch (e) { err('检测启动失败：' + errText(e)) }
}

async function saveSettings() {
  try {
    const r = await api.monSaveSettings({
      watch_auto: settings.value.watch_auto,
      watch_interval_minutes: Number(settings.value.watch_interval_minutes) || 360,
      watch_auto_subscribe: settings.value.watch_auto_subscribe,
      watch_workshop_top: Number(settings.value.watch_workshop_top) || 20,
    })
    if (r.ok) ok('监控设置已保存')
    else err(r.error || '保存失败')
  } catch (e) { err('保存失败：' + errText(e)) }
}

async function subscribeItems(items) {
  const valid = items.filter(Boolean)
  if (!valid.length) { err('没有可订阅的 Mod'); return }
  try {
    const r = await api.monSubscribe(valid)
    if (r.ok) ok(`已加入订阅队列：${r.count} 个`)
    else err(r.error || '订阅失败')
    setTimeout(loadMods, 1500)
  } catch (e) { err('订阅失败：' + errText(e)) }
}
function subscribeEvent(ev) {
  subscribeItems([{ file_id: ev.file_id, appid: ev.appid, title: ev.title }])
}
function subscribeMod(row) {
  subscribeItems([{ file_id: row.published_file_id, appid: row.appid, title: row.title }])
}

async function readAll() {
  try { await api.monReadEvents([]); loadEvents() } catch { /* 静默 */ }
}

function fmtTime(t) { return t ? t.replace('T', ' ') : '—' }
function workshopUrl(appid) { return `https://steamcommunity.com/workshop/browse/?appid=${appid}` }
function modUrl(fid) { return `https://steamcommunity.com/sharedfiles/filedetails/?id=${fid}` }

onMounted(() => {
  loadAll()
  timer = setInterval(refreshProgress, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="card">
    <h2 style="margin:0 0 6px;">更新监控</h2>
    <p class="muted">关注游戏本体 / 工坊与指定 Mod 的更新；命中关键字可自动订阅。所有目标与事件仅保存在本机。</p>

    <!-- 操作条 -->
    <div class="row" style="align-items:center; gap:16px; flex-wrap:wrap; margin-top:12px;">
      <button class="primary" :disabled="running" @click="checkNow">立即检测</button>
      <label><input type="checkbox" v-model="settings.watch_auto" /> 定时自动检测</label>
      <div class="field" style="margin:0;">
        <label>间隔（分钟）</label>
        <input v-model.number="settings.watch_interval_minutes" type="number" min="15" max="10080" style="width:100px;" />
      </div>
      <label><input type="checkbox" v-model="settings.watch_auto_subscribe" /> 命中规则后自动订阅</label>
      <div class="field" style="margin:0;">
        <label>工坊取样数</label>
        <input v-model.number="settings.watch_workshop_top" type="number" min="1" max="50" style="width:90px;" />
      </div>
      <button class="ghost" @click="saveSettings">保存监控设置</button>
      <span class="muted">{{ progress.message }}</span>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>
    <div class="muted" v-if="running" style="margin-top:8px;">检测进度：{{ progress.current }} / {{ progress.total }}</div>

    <!-- 关注游戏 -->
    <h3 style="margin:20px 0 8px;">关注游戏</h3>
    <div class="row" style="align-items:end; gap:12px; flex-wrap:wrap;">
      <div class="field" style="margin:0;">
        <label>游戏 AppID</label>
        <input v-model="gameForm.appid" placeholder="如 730" style="width:120px;" />
      </div>
      <label><input type="checkbox" v-model="gameForm.watch_store" /> 监控本体信息</label>
      <label><input type="checkbox" v-model="gameForm.watch_workshop" /> 监控工坊更新</label>
      <button class="ghost" @click="addGame">添加关注</button>
    </div>
    <div v-if="games.length" class="game-grid" style="margin-top:12px;">
      <div v-for="g in games" :key="g.appid" class="game-card">
        <div class="game-info">
          <div class="game-name">{{ g.name || `#${g.appid}` }}</div>
          <div class="muted">AppID：{{ g.appid }} · {{ g.watch_store ? '本体' : '' }}{{ g.watch_store && g.watch_workshop ? ' / ' : '' }}{{ g.watch_workshop ? '工坊' : '' }}</div>
          <div class="muted" style="margin-top:4px;">上次检查：{{ fmtTime(g.last_checked_at) }}</div>
          <div class="muted desc">{{ g.last_change || '尚未检测' }}</div>
          <div class="mark-cell" style="margin-top:6px;">
            <a class="inline-link" :href="workshopUrl(g.appid)" target="_blank" rel="noopener noreferrer">工坊页 ↗</a>
            <button class="ghost" style="margin-left:8px;" @click="removeGame(g)">移除</button>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="muted" style="padding:12px 0;">尚未关注游戏；填写 AppID 后添加。</div>

    <!-- 关注 Mod -->
    <h3 style="margin:20px 0 8px;">关注 Mod</h3>
    <div class="row" style="align-items:end; gap:12px; flex-wrap:wrap;">
      <div class="field" style="margin:0;">
        <label>工坊文件 ID</label>
        <input v-model="modForm.file_id" placeholder="Published File ID" style="width:160px;" />
      </div>
      <div class="field" style="margin:0;">
        <label>所属 AppID（可选）</label>
        <input v-model="modForm.appid" placeholder="如 730" style="width:120px;" />
      </div>
      <button class="ghost" @click="addMod">关注 Mod</button>
    </div>
    <div v-if="mods.length" class="game-grid" style="margin-top:12px;">
      <div v-for="m in mods" :key="m.published_file_id" class="game-card">
        <div class="game-info">
          <div class="game-name">{{ m.title || `#${m.published_file_id}` }}</div>
          <div class="muted">File ID：{{ m.published_file_id }}<span v-if="m.appid"> · AppID：{{ m.appid }}</span></div>
          <div style="margin:6px 0;">
            <span class="badge" :class="m.subscribed ? 'claimable' : 'owned'">{{ m.subscribed ? '已订阅' : '未订阅' }}</span>
          </div>
          <div class="muted desc">{{ m.change_note || '暂无变更记录' }}</div>
          <div class="mark-cell" style="margin-top:6px;">
            <button class="icon-btn" :title="m.subscribed ? '已订阅' : '一键订阅'" @click="subscribeMod(m)">⤴</button>
            <a class="inline-link" :href="modUrl(m.published_file_id)" target="_blank" rel="noopener noreferrer">详情 ↗</a>
            <button class="ghost" style="margin-left:8px;" @click="removeMod(m)">移除</button>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="muted" style="padding:12px 0;">尚未关注 Mod。</div>

    <!-- 关键字规则 -->
    <h3 style="margin:20px 0 8px;">关键字自动订阅规则</h3>
    <div class="row" style="align-items:end; gap:12px; flex-wrap:wrap;">
      <div class="field" style="margin:0;">
        <label>限定 AppID（留空 = 任意游戏）</label>
        <input v-model="ruleForm.appid" placeholder="0 / 留空" style="width:130px;" />
      </div>
      <div class="field" style="margin:0; flex:1; min-width:180px;">
        <label>关键字（逗号分隔）</label>
        <input v-model="ruleForm.keywords" placeholder="如 chinese, 汉化, 中文" />
      </div>
      <div class="field" style="margin:0;">
        <label>匹配模式</label>
        <select v-model="ruleForm.match_mode">
          <option value="any">任一命中</option>
          <option value="all">全部命中</option>
        </select>
      </div>
      <label><input type="checkbox" v-model="ruleForm.auto_subscribe" /> 自动订阅</label>
      <label><input type="checkbox" v-model="ruleForm.enabled" /> 启用</label>
      <button class="ghost" @click="addRule">保存规则</button>
    </div>
    <div v-if="rules.length" style="margin-top:12px;">
      <table>
        <thead>
          <tr><th>AppID</th><th>关键字</th><th>模式</th><th>自动订阅</th><th>启用</th><th>备注</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rules" :key="r.id">
            <td>{{ r.appid || '任意' }}</td>
            <td>{{ r.keywords }}</td>
            <td class="muted">{{ r.match_mode === 'all' ? '全部' : '任一' }}</td>
            <td>{{ r.auto_subscribe ? '是' : '否' }}</td>
            <td>{{ r.enabled ? '是' : '否' }}</td>
            <td class="muted">{{ r.note }}</td>
            <td><button class="ghost" @click="removeRule(r)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="padding:12px 0;">暂无规则。命中标题 / 标签的 Mod 可按规则自动订阅。</div>

    <!-- 事件流 -->
    <div class="row" style="align-items:center; gap:12px; margin:20px 0 8px;">
      <h3 style="margin:0;">更新动态</h3>
      <select v-model="eventFilter" @change="loadEvents">
        <option value="">全部类型</option>
        <option value="game_store_update">本体更新</option>
        <option value="mod_new">新 Mod</option>
        <option value="mod_update">Mod 更新</option>
        <option value="rule_hit">规则命中</option>
      </select>
      <label><input type="checkbox" v-model="onlyUnread" @change="loadEvents" /> 仅未读</label>
      <button class="ghost" @click="readAll">全部标记已读</button>
    </div>
    <div v-if="events.length">
      <table>
        <thead>
          <tr><th>时间</th><th>类型</th><th>标题</th><th>详情</th><th>动作</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="ev in events" :key="ev.id" :class="{ ignored: ev.seen }">
            <td class="muted">{{ fmtTime(ev.detected_at) }}</td>
            <td><span class="badge" :class="KIND_CLASS[ev.kind] || 'skipped'">{{ KIND_LABEL[ev.kind] || ev.kind }}</span></td>
            <td>{{ ev.title || `#${ev.file_id || ev.appid}` }}</td>
            <td class="muted">{{ ev.detail }}</td>
            <td class="muted">{{ ev.action === 'subscribed' ? '已订阅' : ev.action === 'rule_hit' ? '规则命中' : '—' }}</td>
            <td>
              <button v-if="ev.file_id" class="ghost" @click="subscribeEvent(ev)">订阅</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="text-align:center;padding:30px;">暂无更新动态，点击「立即检测」开始第一次监控。</div>
  </div>
</template>
