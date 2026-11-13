<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { useMsg } from '../useMsg'

const emit = defineEmits(['navigate', 'session-refresh'])

// 与后端 config.LANG_OPTIONS 对齐；商店区由后端自动识别，前端不可手动修改
const LANG_OPTIONS = [
  { code: 'schinese', label: '简体中文' },
  { code: 'tchinese', label: '繁体中文' },
  { code: 'english', label: '英语' },
  { code: 'japanese', label: '日语' },
  { code: 'koreana', label: '韩语' },
  { code: 'russian', label: '俄语' },
  { code: 'german', label: '德语' },
  { code: 'french', label: '法语' },
  { code: 'spanish', label: '西班牙语' },
  { code: 'portuguese', label: '葡萄牙语' },
  { code: 'italian', label: '意大利语' },
  { code: 'polish', label: '波兰语' },
  { code: 'turkish', label: '土耳其语' },
  { code: 'arabic', label: '阿拉伯语' },
  { code: 'thai', label: '泰语' },
  { code: 'vietnamese', label: '越南语' },
]

const form = ref({ api_key: '', steamid: '', cc: 'cn', lang: 'schinese' })
const ownedCount = ref(0)
const status = ref({ has_key: false, has_steamid: false, profile_exists: false })
const loginState = ref({ state: 'idle', message: '', browser: '' })
const { msg, ok, err, errText } = useMsg()
const testing = ref(false)
const saving = ref(false)
const loggingIn = ref(false)
let loginTimer = null
const STEAMID_RE = /^\d{16,18}$/

const LOGIN_STATE_LABEL = {
  idle: '未打开',
  starting: '正在启动浏览器…',
  ready: '等待在窗口中登录 Steam',
  logged_in: '已检测到登录，登录态已留存本机',
  closed: '登录窗口已关闭',
  blocked: '登录被拦截',
  error: '启动失败',
}

function normalizeForm() {
  form.value = {
    ...form.value,
    api_key: (form.value.api_key || '').trim(),
    steamid: (form.value.steamid || '').trim(),
    lang: form.value.lang || 'schinese',
  }
}

function steamidInvalid() {
  const sid = form.value.steamid
  return sid && !STEAMID_RE.test(sid)
}

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
    normalizeForm()
    if (steamidInvalid()) {
      err('SteamID 应为 17 位纯数字（通常 7656119 开头），请检查是否多填了空格或字母')
      return
    }
    const payload = { api_key: form.value.api_key, steamid: form.value.steamid, lang: form.value.lang }
    const r = await api.saveAccount(payload)
    if (r.ok) {
      form.value.cc = r.cc || form.value.cc
      ok(r.cc_detected !== false
        ? '✓ 保存成功，账号信息已写入本机数据库，下次打开无需重新填写'
        : '✓ 已保存；区域暂未能自动识别，' + (r.cc_note || '将沿用默认区'))
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
    normalizeForm()
    if (steamidInvalid()) {
      err('SteamID 应为 17 位纯数字（通常 7656119 开头），请检查是否多填了空格或字母')
      return
    }
    const payload = { api_key: form.value.api_key, steamid: form.value.steamid, lang: form.value.lang }
    const r = await api.testAccount(payload)
    if (r.ok) {
      form.value.cc = r.cc || form.value.cc
      ok(`连接成功，库内 ${r.owned_count} 个本体`)
      await refreshStatus()
    } else err('连接失败：' + (r.error || '未知原因'))
  } catch (e) {
    err('连接失败：' + errText(e))
  } finally {
    testing.value = false
  }
}

async function openLogin() {
  loggingIn.value = true
  try {
    const r = await api.login()
    if (!r.ok) {
      err(r.error || '无法打开登录窗口')
      loggingIn.value = false
      return
    }
    ok('浏览器登录窗口已打开，请在窗口中完成 Steam 登录')
    pollLogin()
  } catch (e) {
    err('打开登录窗口失败：' + errText(e))
    loggingIn.value = false
  }
}

function pollLogin() {
  if (loginTimer) clearInterval(loginTimer)
  loginTimer = setInterval(async () => {
    try {
      const s = await api.loginStatus()
      loginState.value = s
      if (['logged_in', 'closed', 'error', 'blocked'].includes(s.state)) {
        clearInterval(loginTimer)
        loginTimer = null
        loggingIn.value = false
        if (s.state === 'logged_in') {
          ok(s.message || '登录成功，登录态已留存本机')
          await refreshStatus()
        } else if (s.state === 'error') {
          err(s.message || '浏览器启动失败')
        }
      }
    } catch { /* 静默 */ }
  }, 2000)
}

onUnmounted(() => { if (loginTimer) clearInterval(loginTimer) })</script>

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
          <div class="step-sub">{{ status.profile_exists ? '本机已留存登录态' : (LOGIN_STATE_LABEL[loginState.state] || '首次领取时在弹出窗口登录一次') }}</div>
        </div>
      </div>
    </div>

    <div class="row" style="align-items:center; gap:12px; margin:8px 0;">
      <button class="ghost" :disabled="loggingIn" @click="openLogin">
        {{ loggingIn ? '等待登录…' : '打开浏览器登录 Steam' }}
      </button>
      <span class="muted">{{ loginState.message || '' }}</span>
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
        <label>商店区（自动识别）</label>
        <input v-model="form.cc" placeholder="保存后自动识别" disabled />
        <span class="muted hint">根据账号公开资料自动识别所在地区，不可手动修改。</span>
      </div>
      <div class="field">
        <label>界面 / 商店语言</label>
        <select v-model="form.lang">
          <option v-for="opt in LANG_OPTIONS" :key="opt.code" :value="opt.code">{{ opt.label }}</option>
        </select>
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
