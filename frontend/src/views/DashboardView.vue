<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const emit = defineEmits(['navigate'])
const ov = ref({})

async function load() {
  try { ov.value = await api.overview() } catch { /* 静默 */ }
}

const cards = [
  { key: 'candidates', label: '可领 DLC', value: () => ov.value.dlc_claimable || 0, hint: '扫描并领取免费 DLC' },
  { key: 'freegames', label: '限时免费喜加一', value: () => ov.value.free_limited || 0, hint: '商店限免本体' },
  { key: 'workshop', label: '工坊待处理', value: () => ov.value.ws_pending || 0, hint: '批量订阅 / 退订 Mod' },
  { key: 'monitor', label: '监控新动态', value: () => ov.value.watch_unread || 0, hint: '本体 / 工坊 / Mod 更新与命中' },
  { key: 'cleaner', label: '待清理候选', value: () => ov.value.cleaner_candidate || 0, hint: '按时长 / 下架筛选免费游戏' },
]

onMounted(load)
</script>

<template>
  <div class="card">
    <h2 style="margin:0 0 6px;">Steam 工具助手</h2>
    <p class="muted">免费 DLC 领取 · 创意工坊批量订阅 · 库清理，数据仅保存在本机，不上传。</p>

    <div class="stats" style="margin-top:16px; flex-wrap:wrap;">
      <div class="stat" style="min-width:150px;">库内游戏<b>{{ ov.owned || 0 }}</b></div>
      <div class="stat" v-if="ov.last_scan_at">最近扫描<b class="muted" style="font-size:13px;">{{ ov.last_scan_at }}</b></div>
    </div>

    <div class="game-grid">
      <div v-for="c in cards" :key="c.key" class="game-card" style="cursor:pointer;" @click="emit('navigate', c.key)">
        <div class="game-info">
          <div class="game-name">{{ c.label }}</div>
          <div style="font-size:26px; font-weight:700; margin:6px 0;">{{ c.value() }}</div>
          <div class="muted">{{ c.hint }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
