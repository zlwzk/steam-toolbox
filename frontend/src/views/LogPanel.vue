<script setup>
import { onMounted, onUnmounted, ref, nextTick } from 'vue'
import { api } from '../api'

const logs = ref([])
const box = ref(null)
let timer = null
let stickBottom = true

async function refresh() {
  try {
    const r = await api.logs()
    logs.value = r.logs || []
    if (stickBottom) {
      await nextTick()
      if (box.value) box.value.scrollTop = box.value.scrollHeight
    }
  } catch {
    /* 轮询失败静默 */
  }
}

function onScroll() {
  const el = box.value
  if (!el) return
  stickBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
}

async function clear() {
  try {
    await api.clearLogs()
    logs.value = []
  } catch {
    /* 忽略 */
  }
}

function levelClass(level) {
  return { ERROR: 'log-err', WARNING: 'log-warn', INFO: 'log-info' }[level] || 'log-info'
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="card log-card">
    <div class="row" style="justify-content:space-between;align-items:center;">
      <h3 style="margin:0;">运行日志</h3>
      <button class="ghost" @click="clear">清空日志</button>
    </div>
    <div ref="box" class="log-box" @scroll="onScroll">
      <div v-if="!logs.length" class="muted">暂无日志</div>
      <div v-for="(l, i) in logs" :key="i" class="log-line">
        <span class="log-time">{{ l.time }}</span>
        <span class="log-level" :class="levelClass(l.level)">{{ l.level }}</span>
        <span class="log-msg">{{ l.message }}</span>
      </div>
    </div>
  </div>
</template>
