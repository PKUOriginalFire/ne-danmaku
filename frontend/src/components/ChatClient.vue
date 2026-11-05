<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  roomId: {
    type: String,
    required: true,
  },
  authKey: {
    type: String,
    default: '',
  },
})

const containerRef = ref(null)
const messages = ref([])
const loading = ref(true)
const inputValue = ref('')
const senderName = ref('元火子')
const error = ref('')
const clientSocket = ref(null)
const clientSocketOk = ref(false)
const upstreamSocket = ref(null)
const upstreamSocketOk = ref(false)
const clientReconnectAttempts = ref(0)
const upstreamReconnectAttempts = ref(0)
const authToken = ref('')
const settingsSaving = ref(false)
const settingsError = ref('')
const clearingOverlay = ref(false)

const filteredPatterns = computed(() => {
  const keyword = patternFilter.value.trim().toLowerCase()
  if (!keyword)
    return patterns.value

  return patterns.value.filter(p =>
    String(p.pattern || '').toLowerCase().includes(keyword),
  )
})

// Charge panel state
const chargeUserId = ref('')
const chargeCurrency = ref('huo')
const chargeAmount = ref(1)
const chargeLoading = ref(false)
const chargeError = ref('')
const roomUsers = ref([])
const roomUsersLoading = ref(false)

// Ban / Pattern panel state
const moderationPanelOpen = ref(false)

const banUserId = ref('')
const dedupWindow = ref(5)
const dedupHard = ref(false)
const dedupCurrent = ref(null)
const banHard = ref(false)
const bannedUsers = ref([])
const bannedUsersLoading = ref(false)

const patternInput = ref('')
const patternHard = ref(false)
const patterns = ref([])
const patternsLoading = ref(false)
const patternFilter = ref('')

const patternTestInput = ref('')
const patternTestResult = ref(null)

const moderationError = ref('')

const roomSettings = ref({
  overlay_opacity: 100,
  enable_external_emoji: true,
  enable_internal_emoji: true,
  enable_superchat: true,
  enable_gift: true,
  bind_position: true,
})

const MESSAGE_LIMIT = 100
const maxMessageLength = ref(50)  // 默认值，启动后从后端拉取

async function fetchMaxMessageLength() {
  try {
    const resp = await fetch('/api/danmaku/v1/config')
    if (!resp.ok)
      return
    const data = await resp.json()
    if (typeof data.max_message_length === 'number' && data.max_message_length > 0)
      maxMessageLength.value = data.max_message_length
  }
  catch {
    // 保持默认值
  }
}

// 服务端热重载后广播的配置帧：{"type":"config","config_version":N,"max_message_length":M}
function applyConfigFrame(data) {
  if (typeof data?.max_message_length === 'number' && data.max_message_length > 0)
    maxMessageLength.value = data.max_message_length
}

const canSend = computed(() => {
  return upstreamSocket.value
    && clientSocketOk.value
    && inputValue.value.trim()
    && senderName.value.trim()
    && authToken.value.trim()
    && inputValue.value.length <= maxMessageLength.value
})

const hasAuthKey = computed(() => Boolean(authToken.value))
const canSaveSettings = computed(() => upstreamSocketOk.value && hasAuthKey.value && !settingsSaving.value)
const canClearOverlay = computed(() => hasAuthKey.value && !clearingOverlay.value)

function formatMessageText(message) {
  const prefix = message?.blocked ? '[BLOCKED] ' : ''

  if (typeof message?.text === 'string' && message.text.trim())
    return prefix + message.text

  if (message?.type === 'emote')
    return prefix + '[Emoji 消息]'

  if (message?.type === 'superchat')
    return prefix + `[SC] ${message?.cost ?? 0} 元, ${message?.duration ?? 0} 秒`

  if (message?.type === 'gift')
    return prefix + `[礼物] ${message?.gift_name ?? '未知礼物'} x${message?.quantity ?? 1}, cost=${message?.cost ?? 0}`

  if (message?.type === 'settings')
    return '[房间设置同步消息]'

  return prefix + '[非文本消息]'
}

function shouldShowDebugInfo(message) {
  if (!message)
    return false
  return ['emote', 'superchat', 'gift'].includes(message.type) || Boolean(message.is_special)
}

function stringifyDebugInfo(message) {
  try {
    return JSON.stringify(message, null, 2)
  }
  catch {
    return String(message)
  }
}

function resolveMediaUrl(value) {
  if (!value)
    return null
  if (typeof value !== 'string')
    return null
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/'))
    return value
  return `/api/emoji/${value}`
}

function showMessage(msg) {
  messages.value.push(msg)
  if (messages.value.length > MESSAGE_LIMIT)
    messages.value.shift()

  nextTick(() => {
    if (containerRef.value)
      containerRef.value.scrollTop = containerRef.value.scrollHeight
  })
}

function sendMessage() {
  if (inputValue.value.length > maxMessageLength.value) {
    error.value = `弹幕长度不能超过${maxMessageLength.value}字符`
    return
  }

  if (!canSend.value)
    return

  const packet = {
    group: props.roomId,
    danmaku: {
      text: inputValue.value.trim(),
      sender: senderName.value.trim(),
    },
  }

  upstreamSocket.value.send(JSON.stringify(packet))
  inputValue.value = ''
  error.value = ''
}

async function fetchSettings() {
  if (!hasAuthKey.value)
    return

  settingsError.value = ''
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/rooms/${encodeURIComponent(props.roomId)}/settings?token=${encodeURIComponent(authToken.value)}`)
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    roomSettings.value = {
      overlay_opacity: Number(data.overlay_opacity ?? 100),
      enable_external_emoji: Boolean(data.enable_external_emoji ?? true),
      enable_internal_emoji: Boolean(data.enable_internal_emoji ?? true),
      enable_superchat: Boolean(data.enable_superchat ?? true),
      enable_gift: Boolean(data.enable_gift ?? true),
      bind_position: Boolean(data.bind_position ?? true),
    }
  }
  catch (e) {
    settingsError.value = `读取房间设置失败: ${e.message}`
    showMessage({ text: settingsError.value, source: 'system' })
  }
}

async function saveSettings() {
  if (!canSaveSettings.value)
    return

  settingsSaving.value = true
  settingsError.value = ''
  const normalizedOpacity = Math.max(0, Math.min(100, Number(roomSettings.value.overlay_opacity) || 0))
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/rooms/${encodeURIComponent(props.roomId)}/settings?token=${encodeURIComponent(authToken.value)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...roomSettings.value,
        overlay_opacity: normalizedOpacity,
      }),
    })
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    roomSettings.value.overlay_opacity = normalizedOpacity
    showMessage({ text: '房间设置已更新', source: 'system' })
  }
  catch (e) {
    settingsError.value = `保存房间设置失败: ${e.message}`
    showMessage({ text: settingsError.value, source: 'system' })
  }
  finally {
    settingsSaving.value = false
  }
}

async function clearOverlayNow() {
  if (!canClearOverlay.value)
    return

  if (!window.confirm('确认移除当前房间现有的礼物、SC 和弹幕显示吗？'))
    return

  clearingOverlay.value = true
  settingsError.value = ''
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/rooms/${encodeURIComponent(props.roomId)}/clear?token=${encodeURIComponent(authToken.value)}`, {
      method: 'POST',
    })
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    showMessage({ text: '已发送清空指令', source: 'system' })
  }
  catch (e) {
    settingsError.value = `清空失败: ${e.message}`
    showMessage({ text: settingsError.value, source: 'system' })
  }
  finally {
    clearingOverlay.value = false
  }
}

async function fetchRoomUsers() {
  if (!hasAuthKey.value)
    return
  roomUsersLoading.value = true
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/rooms/${encodeURIComponent(props.roomId)}/users?token=${encodeURIComponent(authToken.value)}`)
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    roomUsers.value = data.users || []
  }
  catch (e) {
    showMessage({ text: `获取用户列表失败: ${e.message}`, source: 'system' })
  }
  finally {
    roomUsersLoading.value = false
  }
}

async function chargeUser() {
  if (!hasAuthKey.value || chargeLoading.value)
    return
  const userId = chargeUserId.value.trim()
  if (!userId) {
    chargeError.value = '请输入用户 ID 或从列表选择'
    return
  }
  chargeLoading.value = true
  chargeError.value = ''
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/rooms/${encodeURIComponent(props.roomId)}/charge/${encodeURIComponent(userId)}?token=${encodeURIComponent(authToken.value)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ currency: chargeCurrency.value, amount: Number(chargeAmount.value) }),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => null)
      throw new Error(detail?.detail || `HTTP ${resp.status}`)
    }
    const result = await resp.json()
    const label = chargeCurrency.value === 'huo' ? '燕火' : '燕元'
    showMessage({ text: `充值成功: ${result.user_name} (${result.user_id}) ${label} ${chargeAmount.value}，当前 ${label}=${chargeCurrency.value === 'huo' ? result.huo : result.yuan}`, source: 'system' })
    fetchRoomUsers()
  }
  catch (e) {
    chargeError.value = `充值失败: ${e.message}`
  }
  finally {
    chargeLoading.value = false
  }
}

async function chargeAllUsers() {
  if (!hasAuthKey.value || chargeLoading.value)
    return
  const label = chargeCurrency.value === 'huo' ? '燕火' : '燕元'
  if (!window.confirm(`确认为房间 ${props.roomId} 所有用户充值 ${chargeAmount.value} ${label} 吗？`))
    return
  chargeLoading.value = true
  chargeError.value = ''
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/rooms/${encodeURIComponent(props.roomId)}/charge_all?token=${encodeURIComponent(authToken.value)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ currency: chargeCurrency.value, amount: Number(chargeAmount.value) }),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => null)
      throw new Error(detail?.detail || `HTTP ${resp.status}`)
    }
    const result = await resp.json()
    showMessage({ text: `全房充值成功: ${result.affected_users} 人，每人 +${result.amount} ${label}`, source: 'system' })
    fetchRoomUsers()
  }
  catch (e) {
    chargeError.value = `充值失败: ${e.message}`
  }
  finally {
    chargeLoading.value = false
  }
}

function selectUserForCharge(userId) {
  chargeUserId.value = userId
}

async function fetchBannedUsers() {
  if (!hasAuthKey.value)
    return

  bannedUsersLoading.value = true

  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/rooms/list_banned_users?token=${encodeURIComponent(authToken.value)}`,
    )

    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)

    const data = await resp.json()
    bannedUsers.value = data.banned_users || []
  }
  catch (e) {
    moderationError.value = `获取封禁列表失败: ${e.message}`
  }
  finally {
    bannedUsersLoading.value = false
  }
}

async function fetchPatterns() {
  if (!hasAuthKey.value)
    return

  patternsLoading.value = true

  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/rooms/list_patterns?token=${encodeURIComponent(authToken.value)}`,
    )

    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)

    const data = await resp.json()
    patterns.value = data.patterns || []
  }
  catch (e) {
    moderationError.value = `获取 Pattern 列表失败: ${e.message}`
  }
  finally {
    patternsLoading.value = false
  }
}

async function fetchDedupWindow() {
  moderationError.value = ''
  try {
    const resp = await fetch(`/api/danmaku/v1/admin/config?token=${encodeURIComponent(authToken.value)}`)
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    if (typeof data.dedup_window === 'number') {
      dedupCurrent.value = data.dedup_window
      dedupWindow.value = data.dedup_window
    }
  }
  catch (e) {
    moderationError.value = `读取去重窗口失败: ${e.message}`
  }
}

// 临时 = 只改内存（persist=false）；Hard = 写回 config.json（persist=true）
async function applyDedupWindow() {
  moderationError.value = ''
  const n = Number(dedupWindow.value)
  if (!Number.isFinite(n) || n < 0) {
    moderationError.value = '去重窗口必须是 ≥ 0 的整数（0 = 关闭去重）'
    return
  }
  const win = Math.round(n)
  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/config?token=${encodeURIComponent(authToken.value)}&persist=${dedupHard.value}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dedup_window: win }),
      },
    )
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    dedupCurrent.value = win
    showMessage({
      text: `去重窗口已设为 ${win} 秒${dedupHard.value ? '（已写入配置，永久）' : '（临时，重启失效）'}`,
      source: 'system',
    })
  }
  catch (e) {
    moderationError.value = `设置去重窗口失败: ${e.message}`
  }
}

async function addBanUser() {
  if (!banUserId.value.trim())
    return

  moderationError.value = ''

  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/rooms/ban_user?user_id=${encodeURIComponent(banUserId.value.trim())}&hard=${banHard.value}&token=${encodeURIComponent(authToken.value)}`,
      { method: 'POST' },
    )

    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)

    await fetchBannedUsers()

    showMessage({
      text: `已封禁用户 ${banUserId.value}`,
      source: 'system',
    })

    banUserId.value = ''
  }
  catch (e) {
    moderationError.value = `封禁失败: ${e.message}`
  }
}

async function unbanUser(userId) {
  moderationError.value = ''

  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/rooms/unban_user?user_id=${encodeURIComponent(userId)}&token=${encodeURIComponent(authToken.value)}`,
      { method: 'POST' },
    )

    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)

    await fetchBannedUsers()

    showMessage({
      text: `已解除封禁 ${userId}`,
      source: 'system',
    })
  }
  catch (e) {
    moderationError.value = `解除封禁失败: ${e.message}`
  }
}

async function addPattern() {
  if (!patternInput.value.trim())
    return

  moderationError.value = ''

  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/rooms/append_pattern?pattern=${encodeURIComponent(patternInput.value)}&hard=${patternHard.value}&token=${encodeURIComponent(authToken.value)}`,
      { method: 'POST' },
    )

    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)

    await fetchPatterns()

    showMessage({
      text: `Pattern 已添加`,
      source: 'system',
    })

    patternInput.value = ''
  }
  catch (e) {
    moderationError.value = `添加 Pattern 失败: ${e.message}`
  }
}

async function removePattern(pattern) {
  moderationError.value = ''

  try {
    const resp = await fetch(
      `/api/danmaku/v1/admin/rooms/remove_pattern?pattern=${encodeURIComponent(pattern)}&token=${encodeURIComponent(authToken.value)}`,
      { method: 'POST' },
    )

    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)

    await fetchPatterns()

    showMessage({
      text: `Pattern 已删除`,
      source: 'system',
    })
  }
  catch (e) {
    moderationError.value = `删除 Pattern 失败: ${e.message}`
  }
}

function testPattern() {
  patternTestResult.value = null

  if (!patternInput.value)
    return

  try {
    const regex = new RegExp(patternInput.value, 'i')
    patternTestResult.value = regex.test(patternTestInput.value)
  }
  catch {
    patternTestResult.value = 'invalid'
  }
}

function quickBanFromMessage(message, hard = false) {
  const userId = message?.sender

  if (!userId)
    return

  banUserId.value = userId
  banHard.value = hard
  addBanUser()
}

function connectClientWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://'
  const wsUrl = `${protocol}${window.location.host}/api/danmaku/v1/danmaku/${props.roomId}`

  if (clientSocketOk.value)
    return

  if (clientSocket.value)
    clientSocket.value.close()

  clientSocket.value = new WebSocket(wsUrl)
  clientSocket.value.onopen = () => {
    checkConnectionStatus()
    // 断线期间可能错过配置广播，重连后补拉一次
    fetchMaxMessageLength()
  }
  clientSocket.value.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data?.type === 'config') {
      applyConfigFrame(data)
      return
    }
    showMessage({ ...data, source: 'client' })
  }
  clientSocket.value.onclose = () => {
    checkConnectionStatus()
    const reconnectDelay = Math.min(30000, 2 ** Math.min(clientReconnectAttempts.value, 10) * 1000)
    setTimeout(connectClientWebSocket, reconnectDelay)
    clientReconnectAttempts.value++
  }
  clientSocket.value.onerror = () => {
    clientSocket.value?.close()
  }
}

function connectUpstreamWebSocket() {
  if (!authToken.value)
    return
  if (upstreamSocketOk.value)
    return

  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://'
  const wsUrl = `${protocol}${window.location.host}/api/danmaku/v1/upstream?token=${authToken.value}`

  if (upstreamSocket.value)
    upstreamSocket.value.close()

  upstreamSocket.value = new WebSocket(wsUrl)
  upstreamSocket.value.onopen = () => {
    checkConnectionStatus()
    fetchSettings()
    fetchRoomUsers()
    fetchBannedUsers()
    fetchPatterns()
    fetchMaxMessageLength()
  }
  upstreamSocket.value.onmessage = (event) => {
    const data = JSON.parse(event.data)
    // 防御：配置帧只发给客户端连接，但若将来扇出扩大，这里不能当成聊天卡片渲染
    if (data?.type === 'config') {
      applyConfigFrame(data)
      return
    }
    if (data.error) {
      showMessage({ text: `上游错误: ${data.error}`, source: 'upstream' })
      return
    }
    showMessage({ ...data, source: 'upstream' })
  }
  upstreamSocket.value.onclose = () => {
    checkConnectionStatus()
    if (authToken.value) {
      const reconnectDelay = Math.min(30000, 2 ** upstreamReconnectAttempts.value * 1000)
      setTimeout(connectUpstreamWebSocket, reconnectDelay)
      upstreamReconnectAttempts.value++
    }
  }
  upstreamSocket.value.onerror = () => {
    showMessage({ text: '上游连接失败，请检查Token是否正确', source: 'upstream' })
  }
}

function checkConnectionStatus() {
  const clientConnected = clientSocket.value && clientSocket.value.readyState === WebSocket.OPEN
  clientSocketOk.value = Boolean(clientConnected)
  const upstreamConnected = upstreamSocket.value && upstreamSocket.value.readyState === WebSocket.OPEN
  upstreamSocketOk.value = Boolean(upstreamConnected)

  if (clientConnected || upstreamConnected) {
    if (loading.value) {
      loading.value = false
      clientReconnectAttempts.value = 0
      upstreamReconnectAttempts.value = 0
      const connections = []
      if (clientConnected)
        connections.push('客户端')
      if (upstreamConnected)
        connections.push('上游')
      showMessage({ text: `元火弹幕姬已连接~ (${connections.join('、')})`, source: 'system' })
    }
  }
  else {
    loading.value = true
    showMessage({ text: '元火弹幕姬已断开~', source: 'system' })
  }
}

function connectWebSocket() {
  loading.value = true
  connectClientWebSocket()
  connectUpstreamWebSocket()
}

watch(inputValue, () => {
  if (error.value)
    error.value = ''
})

watch(() => props.authKey, (value) => {
  const normalized = typeof value === 'string' ? value.trim() : ''
  if (normalized !== authToken.value)
    authToken.value = normalized
}, { immediate: true })

watch(moderationPanelOpen, (val) => {
  if (val) {
    fetchBannedUsers()
    fetchPatterns()
  }
})

watch(authToken, () => {
  if (authToken.value) {
    connectUpstreamWebSocket()
  }
  else if (upstreamSocket.value) {
    upstreamSocket.value.close()
  }
})

watch(() => props.roomId, () => {
  clientSocket.value?.close()
  upstreamSocket.value?.close()
  clientReconnectAttempts.value = 0
  upstreamReconnectAttempts.value = 0
  messages.value = []
  connectWebSocket()
})

onMounted(() => {
  fetchMaxMessageLength()
  connectWebSocket()
})

onUnmounted(() => {
  clientSocket.value?.close()
  upstreamSocket.value?.close()
})
</script>

<template>
  <div class="chat-shell">
    <header class="chat-status">
      <div class="status-pill" :class="{ connected: clientSocketOk }">
        <span class="status-dot" :class="{ connected: clientSocketOk }" />
        <span>客户端连接</span>
      </div>
      <div class="status-pill" :class="{ connected: upstreamSocketOk }">
        <span class="status-dot" :class="{ connected: upstreamSocketOk }" />
        <span>上游连接</span>
      </div>
      <span v-if="loading" class="status-note">正在重连...</span>
    </header>

    <section ref="containerRef" class="chat-messages">
      <article v-for="(message, index) in messages" :key="index" class="message-card">
        <header class="message-meta">
          <strong v-if="message.sender" class="message-sender">{{ message.sender }}</strong>
          <span v-if="message?.blocked" class="message-tag blocked">BLOCKED</span>
          <span v-if="message.source" class="message-tag" :class="message.source">
            {{ message.source === 'client' ? '客户端' : message.source === 'upstream' ? '上游' : '系统' }}
          </span>
          <div v-if="hasAuthKey && message.sender" class="message-actions">
            <button class="small-btn" @click="quickBanFromMessage(message, false)">
              Ban
            </button>
            <button class="small-btn danger-mini-btn" @click="quickBanFromMessage(message, true)">
              Hard Ban
            </button>
          </div>
        </header>
        <p class="message-text">{{ formatMessageText(message) }}</p>

        <div v-if="message.type === 'emote'" class="message-media">
          <img :src="resolveMediaUrl(message.emote_url) || 'https://placehold.co/120x120/111827/e5e7eb'" alt="emoji">
        </div>

        <div v-if="message.type === 'gift'" class="message-media">
          <img :src="resolveMediaUrl(message.image_url) || 'https://placehold.co/120x120/374151/e5e7eb'" alt="gift">
        </div>

        <details v-if="shouldShowDebugInfo(message)" class="debug-panel">
          <summary>Debug Info</summary>
          <pre>{{ stringifyDebugInfo(message) }}</pre>
        </details>
      </article>
    </section>

    <section v-if="hasAuthKey" class="opacity-panel">
      <div class="panel-title">房间动态设置</div>
      <label class="slider-label">
        <span>弹幕透明度</span>
        <input v-model.number="roomSettings.overlay_opacity" type="range" min="0" max="100">
        <span class="slider-value">{{ Math.round(roomSettings.overlay_opacity) }}%</span>
      </label>
      <label class="toggle-item"><input v-model="roomSettings.enable_external_emoji" type="checkbox">启用外部
        Emoji（Satori/OneBot）</label>
      <label class="toggle-item"><input v-model="roomSettings.enable_internal_emoji" type="checkbox">启用内部表情（【表情】）</label>
      <label class="toggle-item"><input v-model="roomSettings.enable_superchat" type="checkbox">启用 SuperChat</label>
      <label class="toggle-item"><input v-model="roomSettings.enable_gift" type="checkbox">启用礼物</label>
      <label class="toggle-item"><input v-model="roomSettings.bind_position" type="checkbox">允许置顶/置底定位</label>
      <button class="primary-btn" :disabled="!canSaveSettings" @click="saveSettings">
        {{ settingsSaving ? '保存中...' : '保存设置' }}
      </button>
      <button class="danger-btn" :disabled="!canClearOverlay" @click="clearOverlayNow">
        {{ clearingOverlay ? '清空中...' : '移除现有礼物/SC/弹幕' }}
      </button>
      <div v-if="settingsError" class="error-text">{{ settingsError }}</div>
    </section>

    <section v-if="hasAuthKey" class="charge-panel">
      <div class="panel-title">充值管理</div>

      <div class="charge-user-list">
        <div class="charge-user-list-header">
          <span>房间用户列表</span>
          <button class="small-btn" :disabled="roomUsersLoading" @click="fetchRoomUsers">
            {{ roomUsersLoading ? '刷新中...' : '刷新' }}
          </button>
        </div>
        <div v-if="roomUsers.length === 0" class="empty-list-hint">暂无用户数据</div>
        <div v-else class="user-list-scroll">
          <div v-for="u in roomUsers" :key="u.user_id" class="user-list-item"
            :class="{ selected: chargeUserId === u.user_id }" @click="selectUserForCharge(u.user_id)">
            <span class="user-name">{{ u.user_name }}</span>
            <span class="user-id-tag">{{ u.user_id }}</span>
            <span class="user-balance">元{{ u.yuan.toFixed(1) }} / 火{{ u.huo.toFixed(1) }}</span>
          </div>
        </div>
      </div>

      <div class="charge-form">
        <input v-model="chargeUserId" class="text-input" type="text" placeholder="用户 ID（或从上方选择）">
        <select v-model="chargeCurrency" class="text-input">
          <option value="huo">燕火</option>
          <option value="yuan">燕元</option>
        </select>
        <input v-model.number="chargeAmount" class="text-input" type="number" step="0.1" placeholder="充值数量">
        <button class="primary-btn" :disabled="chargeLoading || !chargeUserId.trim()" @click="chargeUser">
          {{ chargeLoading ? '充值中...' : '充值该用户' }}
        </button>
        <button class="warn-btn" :disabled="chargeLoading" @click="chargeAllUsers">
          {{ chargeLoading ? '充值中...' : '充值全房间' }}
        </button>
      </div>
      <div v-if="chargeError" class="error-text">{{ chargeError }}</div>
    </section>

    <section v-if="hasAuthKey" class="moderation-panel">
      <div class="panel-title moderation-title">
        <span>弹幕过滤 / 封禁管理</span>

        <button class="primary-btn" @click="moderationPanelOpen = true">
          打开管理面板
        </button>
      </div>
    </section>

    <div v-if="moderationPanelOpen" class="moderation-modal-mask" @click.self="moderationPanelOpen = false">
      <div class="moderation-modal">
        <div class="moderation-modal-header">
          <div class="panel-title">
            弹幕过滤 / 封禁管理
          </div>

          <button class="small-btn" @click="moderationPanelOpen = false">
            关闭
          </button>
        </div>

        <div class="moderation-modal-body">
          <div class="moderation-grid">
            <div class="moderation-card">
              <div class="sub-title">添加封禁用户</div>

              <div class="inline-form">
                <input v-model="banUserId" class="text-input" type="text" placeholder="用户 ID">

                <label class="toggle-item">
                  <input v-model="banHard" type="checkbox">
                  Hard
                </label>

                <button class="danger-btn" @click="addBanUser">
                  Ban
                </button>
              </div>

              <div class="sub-title row-title">
                <span>已封禁用户</span>

                <button class="small-btn" :disabled="bannedUsersLoading" @click="fetchBannedUsers">
                  {{ bannedUsersLoading ? '刷新中' : '刷新' }}
                </button>
              </div>

              <div class="user-list-scroll modal-scroll">
                <div v-for="u in bannedUsers" :key="u.user_id" class="user-list-item">
                  <div class="ban-user-info">
                    <span class="user-name">{{ u.user_id }}</span>

                    <div class="ban-user-tags">
                      <span class="mini-tag" :class="u.in_memory ? 'tag-green' : 'tag-red'">
                        memory
                      </span>

                      <span class="mini-tag" :class="u.in_file ? 'tag-green' : 'tag-red'">
                        file
                      </span>
                    </div>
                  </div>

                  <button class="small-btn" @click="unbanUser(u.user_id)">
                    Unban
                  </button>
                </div>
              </div>
            </div>

            <div class="moderation-card">
              <div class="sub-title row-title">
                <span>去重时间窗口</span>

                <button class="small-btn" @click="fetchDedupWindow">
                  读取
                </button>
              </div>

              <div class="inline-form">
                <input v-model.number="dedupWindow" class="text-input" type="number" min="0" step="1" placeholder="秒（0 = 关闭去重）">

                <label class="toggle-item">
                  <input v-model="dedupHard" type="checkbox">
                  Hard
                </label>

                <button class="small-btn" @click="applyDedupWindow">
                  应用
                </button>
              </div>

              <div style="opacity: .7; font-size: .85em; margin-top: .4rem;">
                当前：{{ dedupCurrent === null ? '未读取（点「读取」）' : dedupCurrent + ' 秒' }}
                · 临时 = 只改内存（重启失效）· Hard = 写入 config.json（永久）
              </div>
            </div>

            <div class="moderation-card">
              <div class="sub-title">Pattern 管理</div>

              <div class="inline-form">
                <input v-model="patternInput" class="text-input" type="text" placeholder="正则表达式">

                <label class="toggle-item">
                  <input v-model="patternHard" type="checkbox">
                  Hard
                </label>

                <button class="primary-btn" @click="addPattern">
                  添加
                </button>
              </div>

              <div class="inline-form">
                <input v-model="patternTestInput" class="text-input" type="text" placeholder="测试字符串">

                <button class="small-btn" @click="testPattern">
                  测试
                </button>

                <span v-if="patternTestResult !== null" class="test-result">
                  {{
                    patternTestResult === 'invalid'
                    ? '正则非法'
                    : patternTestResult
                      ? '匹配成功'
                      : '未匹配'
                  }}
                </span>
              </div>

              <div class="inline-form">
                <input v-model="patternFilter" class="text-input" type="text" placeholder="筛选 Pattern">

                <button class="small-btn" :disabled="patternsLoading" @click="fetchPatterns">
                  {{ patternsLoading ? '刷新中' : '刷新' }}
                </button>
              </div>

              <div class="pattern-scroll modal-scroll">
                <div v-for="p in filteredPatterns" :key="p.pattern" class="pattern-item">
                  <div class="pattern-info">
                    <code>{{ p.pattern }}</code>

                    <div class="pattern-tags">
                      <span class="mini-tag" :class="p.correct ? 'tag-green' : 'tag-red'">
                        {{ p.correct ? 'valid' : 'invalid' }}
                      </span>

                      <span class="mini-tag" :class="p.in_memory ? 'tag-green' : 'tag-red'">
                        memory
                      </span>

                      <span class="mini-tag" :class="p.in_file ? 'tag-green' : 'tag-red'">
                        file
                      </span>
                    </div>
                  </div>

                  <button class="small-btn" @click="removePattern(p.pattern)">
                    删除
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="moderationError" class="error-text">
            {{ moderationError }}
          </div>
        </div>
      </div>
    </div>

    <section class="composer">
      <div class="auth-hint" :class="{ ready: hasAuthKey }">
        {{ hasAuthKey ? 'URL key 已加载' : '缺少 URL key，无法连接上游' }}
      </div>
      <input v-model="senderName" class="text-input" type="text" placeholder="输入昵称...">
      <input v-model="inputValue" class="text-input" type="text" :maxlength="maxMessageLength" placeholder="输入弹幕..."
        @keydown.enter="sendMessage">
      <button class="primary-btn" :disabled="!canSend" @click="sendMessage">
        发送数据包
      </button>
      <div v-if="error" class="error-text">{{ error }}</div>
    </section>

    <div v-if="inputValue" class="char-counter">
      {{ inputValue.length }}/{{ maxMessageLength }}
    </div>
  </div>
</template>

<style scoped>
.chat-shell {
  height: 100vh;
  width: 100vw;
  display: flex;
  flex-direction: column;
  background: rgba(2, 6, 23, 0.75);
  backdrop-filter: blur(18px);
  color: #e2e8f0;
}

.chat-status {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  align-items: center;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 0.9rem;
  background: rgba(148, 163, 184, 0.18);
  color: #94a3b8;
}

.status-pill.connected {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.8);
}

.status-dot.connected {
  background: #22c55e;
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.8);
}

.status-note {
  margin-left: auto;
  font-size: 0.85rem;
  color: #fbbf24;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message-card {
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid rgba(148, 163, 184, 0.15);
  box-shadow: 0 8px 20px rgba(2, 6, 23, 0.45);
}

.message-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 6px;
}

.message-sender {
  color: #93c5fd;
}

.message-text {
  margin: 0;
  line-height: 1.5;
}

.message-media {
  margin-top: 8px;
}

.message-media img {
  width: 84px;
  height: 84px;
  object-fit: contain;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.25);
}

.debug-panel {
  margin-top: 10px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 6px 10px;
  background: rgba(2, 6, 23, 0.5);
}

.debug-panel summary {
  cursor: pointer;
  color: #cbd5e1;
  font-size: 0.85rem;
}

.debug-panel pre {
  margin: 8px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #93c5fd;
  font-size: 0.8rem;
}

.message-tag {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.75rem;
  text-transform: uppercase;
}

.message-tag.client {
  background: rgba(14, 165, 233, 0.2);
  color: #38bdf8;
}

.message-tag.upstream {
  background: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
}

.message-tag.system {
  background: rgba(148, 163, 184, 0.2);
  color: #cbd5f5;
}

.message-tag.blocked {
  background: rgba(239, 68, 68, 0.25);
  color: #fca5a5;
}

.message-text {
  margin: 0;
  color: #e2e8f0;
  line-height: 1.5;
}

.opacity-panel {
  padding: 18px 20px;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(15, 23, 42, 0.55);
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  align-items: center;
}

.panel-title {
  font-weight: 600;
  color: #f8fafc;
  grid-column: 1 / -1;
}

.slider-label {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #cbd5f5;
  grid-column: 1 / -1;
}

.slider-label input[type='range'] {
  flex: 1;
}

.slider-value {
  width: 50px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.toggle-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #cbd5f5;
}

.composer {
  padding: 16px 20px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  align-items: center;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
}

.auth-hint {
  padding: 10px 14px;
  border-radius: 10px;
  text-align: center;
  font-size: 0.9rem;
  border: 1px dashed rgba(248, 250, 252, 0.4);
}

.auth-hint.ready {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  border-color: rgba(34, 197, 94, 0.4);
}

.text-input {
  width: 100%;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(15, 23, 42, 0.4);
  color: #f1f5f9;
  font-size: 1rem;
}

.text-input:focus {
  outline: none;
  border-color: rgba(99, 102, 241, 0.7);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
}

.primary-btn {
  padding: 12px 20px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(120deg, #6366f1, #8b5cf6);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.primary-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 30px rgba(79, 70, 229, 0.35);
}

.danger-btn {
  padding: 12px 20px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(120deg, #dc2626, #f97316);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.danger-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.danger-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 30px rgba(239, 68, 68, 0.35);
}

.error-text {
  grid-column: 1 / -1;
  color: #f87171;
  font-size: 0.9rem;
}

.char-counter {
  text-align: right;
  padding: 0 20px 16px;
  color: #94a3b8;
  font-size: 0.85rem;
  letter-spacing: 0.05em;
}

.charge-panel {
  padding: 18px 20px;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.charge-user-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #cbd5f5;
  font-size: 0.9rem;
}

.small-btn {
  padding: 4px 12px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.4);
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.8rem;
}

.small-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.2);
  color: #c7d2fe;
}

.small-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.user-list-scroll {
  max-height: 180px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
}

.user-list-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(148, 163, 184, 0.12);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.user-list-item:hover {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.3);
}

.user-list-item.selected {
  background: rgba(99, 102, 241, 0.25);
  border-color: rgba(99, 102, 241, 0.5);
}

.user-name {
  color: #93c5fd;
  font-weight: 500;
}

.user-id-tag {
  color: #64748b;
  font-size: 0.8rem;
}

.user-balance {
  margin-left: auto;
  color: #94a3b8;
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.empty-list-hint {
  color: #64748b;
  font-size: 0.85rem;
  text-align: center;
  padding: 16px 0;
}

.charge-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  align-items: center;
}

.charge-form select {
  appearance: auto;
}

.warn-btn {
  padding: 12px 20px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(120deg, #f59e0b, #f97316);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.warn-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.warn-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 30px rgba(245, 158, 11, 0.35);
}

.message-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

.danger-mini-btn {
  background: rgba(220, 38, 38, 0.2);
  color: #fca5a5;
}

.moderation-panel {
  padding: 18px 20px;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(15, 23, 42, 0.55);
}

.moderation-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.moderation-grid {
  flex: 1;

  min-height: 0;

  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;

  overflow: hidden;
}

.sub-title {
  color: #e2e8f0;
  font-weight: 600;
}

.inline-form {
  display: flex;
  gap: 10px;
  align-items: center;
}

.pattern-scroll {
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pattern-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.4);
}

.pattern-item code {
  color: #93c5fd;
  word-break: break-all;
}

.test-result {
  color: #cbd5f5;
  font-size: 0.9rem;
}

.row-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pattern-info,
.ban-user-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.pattern-tags,
.ban-user-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.mini-tag {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.72rem;
  line-height: 1.2;
}

.tag-green {
  background: rgba(34, 197, 94, 0.18);
  color: #86efac;
}

.tag-red {
  background: rgba(239, 68, 68, 0.18);
  color: #fca5a5;
}

.moderation-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(2, 6, 23, 0.75);
  backdrop-filter: blur(8px);
  z-index: 2000;

  display: flex;
  align-items: center;
  justify-content: center;

  padding: 24px;
}

.moderation-modal {
  width: min(1200px, 92vw);
  height: min(820px, 88vh);

  display: flex;
  flex-direction: column;

  overflow: hidden;
}

.moderation-modal-header {
  padding: 18px 22px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);

  display: flex;
  align-items: center;
  justify-content: space-between;
}

.moderation-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.modal-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.moderation-card {
  padding: 14px;
  border-radius: 12px;
  background: rgba(2, 6, 23, 0.45);
  border: 1px solid rgba(148, 163, 184, 0.12);

  display: flex;
  flex-direction: column;

  min-height: 0;
}

.moderation-modal-body {
  flex: 1;
  min-height: 0;

  overflow: hidden;

  padding: 16px;
}
</style>
