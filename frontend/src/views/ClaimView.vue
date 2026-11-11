<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const prog = ref({ state: 'idle', total: 0, current: 0, message: '', counts: {} })
const records = ref([])
const logging = ref(false)
const { msg, ok, err, errText } = useMsg()
let timer = null

const running = computed(() => prog.value.state === 'running')
const resumable = computed(() => !!prog.value.resumable && !running.value)
const pct = computed(() => (prog.value.total ? Math.round((prog.value.current / prog.value.total) * 100) : 0))

async function resume() {
  try {
    const r = await api.resumeClaim()
    if (r.ok) ok(`已继续领取剩余 ${r.count} 个条目`)
    else err(r.error || '无法继续领取')
    refresh()
  } catch (e) {
    err('继续领取失败：' + errText(e))
  }
}

async function refresh() {
  try {
    prog.value = await api.claimProgress()
    records.value = await api.claimRecords()
  } catch {
    /* 轮询失败静默，等待下一次 */
  }
}

async function login() {
  logging.value = true
  try {
    await api.login()
    ok('已打开登录浏览器，请在窗口中完成 Steam 登录')
  } catch (e) {
    err('打开登录浏览器失败：' + errText(e))
  } finally {
    logging.value = false
  }
}

function exportRecords() {
  window.open(api.exportUrl('claim', {}))
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="card">
    <h2>领取与记录</h2>
    <p class="muted">首次使用请先打开浏览器登录 Steam；领取严格串行、按设置限速，遇验证码或登录墙会自动暂停转人工。</p>

    <div class="row" style="align-items:center; gap:16px;">
      <button class="ghost" :disabled="logging" @click="login">
        {{ logging ? '正在打开浏览器…' : '登录 Steam' }}
      </button>
      <button v-if="resumable" class="primary" @click="resume">
        继续领取剩余（{{ prog.remaining || 0 }}）
      </button>
      <button @click="exportRecords">导出记录 CSV</button>
      <span class="muted">{{ prog.message }}</span>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>
    <div class="muted" v-if="resumable" style="margin-top:8px;">
      上次领取未完成，剩余条目已保留在本机；继续时会自动跳过已成功 / 已在库的条目，不重复领取。
    </div>

    <div class="progress" v-if="running" style="margin:16px 0;">
      <span :style="{ width: pct + '%' }"></span>
    </div>
    <div class="muted" v-if="running">进度：{{ prog.current }} / {{ prog.total }}</div>

    <div class="stats" style="margin-top:16px;">
      <div class="stat">成功<b>{{ prog.counts.success || 0 }}</b></div>
      <div class="stat">失败<b>{{ prog.counts.failed || 0 }}</b></div>
      <div class="stat">跳过<b>{{ prog.counts.skipped || 0 }}</b></div>
      <div class="stat">受阻<b>{{ prog.counts.blocked || 0 }}</b></div>
    </div>

    <table style="margin-top:16px;">
      <thead>
        <tr>
          <th>AppID</th>
          <th>类型</th>
          <th>状态</th>
          <th>原因</th>
          <th>时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in records" :key="r.id">
          <td>{{ r.dlc_appid }}</td>
          <td class="muted">{{ r.item_kind }}</td>
          <td><span class="badge" :class="r.status">{{ r.status }}</span></td>
          <td class="muted">{{ r.reason }}</td>
          <td class="muted">{{ r.claimed_at }}</td>
        </tr>
        <tr v-if="!records.length">
          <td colspan="5" class="muted" style="text-align:center;padding:30px;">暂无领取记录</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
