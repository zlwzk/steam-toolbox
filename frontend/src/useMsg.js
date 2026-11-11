import { ref } from 'vue'

/**
 * 统一操作结果提示。
 * msg.value = { text, type }，type: 'ok' | 'err' | 'info'
 * 成功 / 普通信息 4 秒后自动清除；失败提示保留到下一次操作。
 */
export function useMsg() {
  const msg = ref({ text: '', type: '' })
  let timer = null

  function clearLater() {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      msg.value = { text: '', type: '' }
      timer = null
    }, 4000)
  }

  function set(text, type = 'info', autoClear = true) {
    msg.value = { text: String(text ?? ''), type }
    if (autoClear) clearLater()
  }

  const ok = (text) => set(text, 'ok')
  const err = (text) => set(text, 'err', false)
  const info = (text) => set(text, 'info')

  /** 把请求异常归一化为简短可读文案 */
  function errText(exc) {
    const raw = exc && exc.message ? exc.message : String(exc ?? '未知错误')
    const oneLine = raw.replace(/\s+/g, ' ').trim()
    return oneLine.length > 160 ? oneLine.slice(0, 160) + '…' : oneLine
  }

  return { msg, set, ok, err, info, errText }
}
