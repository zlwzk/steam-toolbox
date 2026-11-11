<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const form = ref({})
const { msg, ok, err, errText } = useMsg()
const sched = ref({})
const saving = ref(false)

const fetchFields = [
  { key: 'fetch_concurrency', label: '抓取并发线程数（1–5）' },
  { key: 'fetch_delay_min', label: '抓取最小间隔（秒）' },
  { key: 'fetch_delay_max', label: '抓取最大间隔（秒）' },
  { key: 'cache_ttl_hours', label: '详情缓存有效期（小时）' },
  { key: 'free_game_pages', label: '喜加一搜索页数（每页 50）' },
]
const claimFields = [
  { key: 'claim_hourly_limit', label: '每小时领取上限' },
  { key: 'claim_delay_min', label: '领取最小间隔（秒）' },
  { key: 'claim_delay_max', label: '领取最大间隔（秒）' },
  { key: 'claim_batch_size', label: '每批数量' },
  { key: 'batch_rest_min', label: '批间休息最小（秒）' },
  { key: 'batch_rest_max', label: '批间休息最大（秒）' },
  { key: 'max_retries', label: '失败重试次数' },
]
const wsFields = [
  { key: 'ws_delay_min', label: '工坊单项最小间隔（秒）' },
  { key: 'ws_delay_max', label: '工坊单项最大间隔（秒）' },
  { key: 'ws_batch_size', label: '工坊每批数量' },
  { key: 'ws_cooldown_min', label: '工坊批间休息最小（秒）' },
  { key: 'ws_cooldown_max', label: '工坊批间休息最大（秒）' },
  { key: 'ws_max_retries', label: '工坊失败重试次数' },
  { key: 'ws_max_pages', label: '工坊自动翻页上限（页）' },
]

onMounted(async () => {
  try {
    form.value = await api.getSettings()
    sched.value = await api.schedulerStatus()
  } catch (e) {
    err('读取设置失败：' + errText(e))
  }
})

async function save() {
  saving.value = true
  try {
    await api.saveSettings(form.value)
    sched.value = await api.schedulerStatus()
    ok('✓ 设置已保存')
  } catch (e) {
    err('保存失败：' + errText(e))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="card">
    <h2>速率与风控设置</h2>
    <p class="muted">数值为保守默认值，调整后即时生效。</p>

    <h3>抓取阶段（盘点）</h3>
    <div class="row">
      <div class="field" v-for="f in fetchFields" :key="f.key">
        <label>{{ f.label }}</label>
        <input v-model="form[f.key]" type="number" step="0.1" />
      </div>
    </div>

    <h3>领取阶段</h3>
    <div class="row">
      <div class="field" v-for="f in claimFields" :key="f.key">
        <label>{{ f.label }}</label>
        <input v-model="form[f.key]" type="number" step="0.1" />
      </div>
    </div>

    <h3>创意工坊批量订阅</h3>
    <div class="row">
      <div class="field" v-for="f in wsFields" :key="f.key">
        <label>{{ f.label }}</label>
        <input v-model="form[f.key]" type="number" step="0.1" />
      </div>
    </div>

    <h3>库清理默认</h3>
    <div class="row">
      <div class="field">
        <label>时长单位</label>
        <select v-model="form.cleaner_unit">
          <option value="minute">分钟</option>
          <option value="hour">小时</option>
        </select>
      </div>
      <div class="field">
        <label>下架 / 绝版默认策略</label>
        <select v-model="form.cleaner_exclude_delisted">
          <option value="keep">不排除</option>
          <option value="exclude">排除已下架</option>
          <option value="only">仅看已下架</option>
        </select>
      </div>
    </div>

    <h3>定时巡检</h3>
    <div class="row">
      <div class="field">
        <label>自动巡检</label>
        <select v-model="form.auto_scan">
          <option value="false">关闭</option>
          <option value="true">开启</option>
        </select>
      </div>
      <div class="field">
        <label>巡检间隔（分钟）</label>
        <input v-model="form.scan_interval_minutes" type="number" step="30" />
      </div>
      <div class="field">
        <label>巡检范围</label>
        <select v-model="form.scan_kind">
          <option value="both">DLC + 喜加一（交替）</option>
          <option value="dlc">仅 DLC</option>
          <option value="freegame">仅喜加一</option>
        </select>
      </div>
    </div>
    <div class="muted" v-if="sched.last_run_at">
      上次巡检：{{ sched.last_run_at }}（{{ sched.last_kind }}）｜ 预计下次：{{ sched.next_run_at || '—' }}
    </div>

    <h3>通知</h3>
    <div class="row">
      <div class="field" style="flex:1;">
        <label>完成通知 Webhook（Bark / Server酱 / 通用 JSON，留空关闭）</label>
        <input v-model="form.notify_webhook" placeholder="https://…" />
      </div>
      <div class="field">
        <label>发送通知</label>
        <select v-model="form.notify_on_done">
          <option value="true">开启</option>
          <option value="false">关闭</option>
        </select>
      </div>
    </div>

    <h3>高级</h3>
    <div class="row">
      <div class="field">
        <label>校验 SSL 证书</label>
        <select v-model="form.verify_ssl">
          <option value="false">关闭（默认；本机缺受信 CA 时避免握手失败）</option>
          <option value="true">开启（网络环境证书链完整时可用）</option>
        </select>
      </div>
      <div class="field">
        <label>领取 / 登录浏览器</label>
        <select v-model="form.browser_channel">
          <option value="msedge">Microsoft Edge（默认）</option>
          <option value="chrome">Google Chrome</option>
          <option value="chromium">自带 Chromium</option>
        </select>
      </div>
      <div class="field">
        <label>领取浏览器无头模式</label>
        <select v-model="form.claim_headless">
          <option value="false">有头（首次登录建议）</option>
          <option value="true">无头</option>
        </select>
      </div>
    </div>

    <div class="row" style="margin-top:10px;">
      <button class="primary" :disabled="saving" @click="save">
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
      <span class="msg" :class="'msg-' + msg.type" v-if="msg.text">{{ msg.text }}</span>
    </div>
  </div>
</template>
