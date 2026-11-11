<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const emit = defineEmits(['navigate', 'session-refresh'])
const form = ref({ api_key: '', steamid: '', cc: 'cn', lang: 'schinese' })
const ownedCount = ref(0)
const status = ref({ has_key: false, has_steamid: false, profile_exists: false })
const { msg, ok, err, errText } = useMsg()
const testing = ref(false)
const saving = ref(false)

onMounted(async () => {
  try {
    const [a, s] = await Promise.all([api.getAccount(), api.sessionStatus()])
    form.value = { api_key: '', steamid: a.steamid, cc: a.cc, lang: a.lang }
    ownedCount.value = a.owned_count
    status.value = {
      has_key: a.has_key,
      has_steamid: a.has_steamid,
      profile_exists: s.profile_exists,
    }
  } catch (e) {
    err('读取账号信息失败：' + errText(e))
  }
})

async function refreshStatus() {
  try {
    const [a, s] = await Promise.all([api.getAccount(), api.sessionStatus()])
    ownedCount.value = a.owned_count
    form.value.steamid = a.steamid
    form.value.cc = a.cc
    form.value.lang = a.lang
    status.value = {
      has_key: a.has_key,
      has_steamid: a.has_steamid,
      profile_exists: s.profile_exists,
    }
  } catch { /* 静默 */ }
  emit('session-refresh')
}

async function save() {
  saving.value = true
  try {
    const r = await api.saveAccount(form.value)
    if (r.ok) {
      ok('✓ 保存成功，账号信息已写入本机数据库，下次打开无需重新填写')
      await refreshStatus()
    } else {
      err('保存失败：' + (r.error || '未知原因'))
    }
  } catch (e) {
    err('保存失败：' + errText(e))
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  try {
    const r = await api.testAccount(form.value)
    if (r.ok) {
      ok(`连接成功，库内 ${r.owned_count} 个本体`)
      await refreshStatus()
    } else err('连接失败：' + (r.error || '未知原因'))
  } catch (e) {
    err('连接失败：' + errText(e))
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="card">
    <h2>账号绑定</h2>

    <div class="steps">
      <div class="step" :class="{ done: status.has_steamid }">
        <span class="step-dot">{{ status.has_steamid ? '✓' : '1' }}</span>
        <div>
          <div class="step-name">SteamID</div>
          <div class="step-sub">{{ status.has_steamid ? '已填写' : '待填写 17 位 ID' }}</div>
        </div>
      </div>
      <div class="step" :class="{ done: status.has_key }">
        <span class="step-dot">{{ status.has_key ? '✓' : '2' }}</span>
        <div>
          <div class="step-name">Web API Key</div>
          <div class="step-sub">{{ status.has_key ? '已保存' : '待申请并粘贴' }}</div>
        </div>
      </div>
      <div class="step" :class="{ done: status.profile_exists }">
        <span class="step-dot">{{ status.profile_exists ? '✓' : '3' }}</span>
        <div>
          <div class="step-name">浏览器登录态</div>
          <div class="step-sub">{{ status.profile_exists ? '本机已留存登录态' : '首次领取时在弹出窗口登录一次' }}</div>
        </div>
      </div>
    </div>

    <p class="muted">使用你自己的 Steam Web API Key 拉取游戏库；Key 仅保存在本机数据库，不上传。</p>

    <div class="field">
      <label>
        Steam Web API Key（留空则不修改已保存的 Key）
        <a class="inline-link" href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener noreferrer">
          前往申请 Key →
        </a>
      </label>
      <input v-model="form.api_key" type="password" placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
      <span class="muted hint">打开申请页登录后，域名可填 <code>localhost</code>，提交后复制生成的 Key 粘贴到此处。</span>
    </div>
    <div class="field">
      <label>
        SteamID（17 位数字）
        <a class="inline-link" href="https://steamcommunity.com/my/edit/settings" target="_blank" rel="noopener noreferrer">
          打开个人主页 →
        </a>
      </label>
      <input v-model="form.steamid" placeholder="7656119xxxxxxxxxx" />
      <span class="muted hint">在 Steam 个人主页的链接中，<code>7656119</code> 开头的 17 位数字即为 SteamID。</span>
    </div>
    <div class="row">
      <div class="field">
        <label>商店区（cc）</label>
        <input v-model="form.cc" placeholder="cn" />
      </div>
      <div class="field">
        <label>语言（l）</label>
        <input v-model="form.lang" placeholder="schinese" />
      </div>
    </div>

    <div class="row">
      <button class="primary" :disabled="saving" @click="save">
        {{ saving ? '保存中…' : '保存' }}
      </button>
      <button class="ghost" :disabled="testing" @click="test">
        {{ testing ? '测试中…' : '测试连接' }}
      </button>
      <button class="ghost" @click="emit('navigate','scan')">前往扫描盘点 →</button>
      <span class="muted" v-if="ownedCount">已入库本体：{{ ownedCount }}</span>
    </div>
    <div class="row" v-if="msg.text">
      <span class="msg" :class="'msg-' + msg.type">{{ msg.text }}</span>
    </div>
  </div>
</template>
