<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

// =======================
// Props 定义
// =======================

// 组件接收的参数
const props = defineProps({
  // 房间 ID，用于区分不同弹幕房间
  roomId: {
    type: String,
    required: true, // 必须提供
  },
  // 上游认证用的密钥
  authKey: {
    type: String,
    default: '', // 默认为空字符串
  },
})

// =======================
// 响应式状态定义
// =======================

// 消息显示容器的 DOM 引用
const containerRef = ref(null)
// 当前显示的消息列表
const messages = ref([])
// 是否处于加载 / 重连状态
const loading = ref(true)
// 输入框中的弹幕内容
const inputValue = ref('')
// 发送者昵称
const senderName = ref('元火子')
// 错误提示文本
const error = ref('')
// 客户端（下游）WebSocket 实例
const clientSocket = ref(null)
// 客户端 WebSocket 是否已连接
const clientSocketOk = ref(false)
// 上游 WebSocket 实例（用于发送弹幕 / 控制指令）
const upstreamSocket = ref(null)
// 上游 WebSocket 是否已连接
const upstreamSocketOk = ref(false)
// 当前重连尝试次数（客户端与上游共用）
const reconnectAttempts = ref(0)
// 实际使用的认证 Token（来自 props.authKey）
const authToken = ref('')
// 全局弹幕透明度（0~100）
const opacityValue = ref(100)

// =======================
// 常量配置
// =======================

// 最多保留的消息条数
const MESSAGE_LIMIT = 100
// 单条弹幕允许的最大长度
const MAX_MESSAGE_LENGTH = 50

// =======================
// 计算属性
// =======================

// 是否满足发送弹幕的所有条件
const canSend = computed(() => {
  return upstreamSocket.value
    && clientSocketOk.value
    && inputValue.value.trim() // 输入内容不为空
    && senderName.value.trim() // 发送者名称不为空
    && authToken.value.trim() // 已通过认证
    && inputValue.value.length <= MAX_MESSAGE_LENGTH // 长度合法
})

// 是否存在有效的认证 Token
const hasAuthKey = computed(() => Boolean(authToken.value))
// 是否允许发送透明度控制命令（影响 UI 可用性）
const canSendOpacity = computed(() => upstreamSocketOk.value && hasAuthKey.value)

// =======================
// 消息显示逻辑
// =======================

// 将一条消息加入消息列表并滚动到底部
function showMessage(msg) {
  messages.value.push(msg)

  // 超过最大条数时移除最早的一条
  if (messages.value.length > MESSAGE_LIMIT)
    messages.value.shift()

  // 等待 DOM 更新后滚动到最底部
  nextTick(() => {
    if (containerRef.value)
      containerRef.value.scrollTop = containerRef.value.scrollHeight
  })
}

// =======================
// 弹幕与控制指令发送
// =======================

// 发送普通弹幕消息
function sendMessage() {
  // 本地长度校验（防止误发送）
  if (inputValue.value.length > MAX_MESSAGE_LENGTH) {
    error.value = `弹幕长度不能超过${MAX_MESSAGE_LENGTH}字符`
    return
  }

  // 条件不满足时直接返回
  if (!canSend.value)
    return

  // 构造弹幕数据包
  const packet = {
    group: props.roomId,
    danmaku: {
      text: inputValue.value.trim(),
      sender: senderName.value.trim(),
    },
  }

  // 通过上游 WebSocket 发送
  upstreamSocket.value.send(JSON.stringify(packet))

  // 发送后清理输入状态
  inputValue.value = ''
  error.value = ''
}

// 发送全局透明度控制命令
function sendOpacityCommand() {
  // 条件不满足时直接返回
  if (!canSendOpacity.value || !upstreamSocket.value)
    return

  // 将透明度规范到 0~100 的整数范围
  const normalized = Math.max(0, Math.min(100, Number(opacityValue.value) || 0))

  // 构造控制指令数据包
  const packet = {
    group: props.roomId,
    control: {
      type: 'setOpacity',
      value: normalized,
    },
  }

  // 发送控制指令
  upstreamSocket.value.send(JSON.stringify(packet))

  // 本地显示系统提示
  showMessage({ text: `已设置全局透明度为 ${normalized}%`, source: 'system' })
}

// =======================
// 客户端（下游）WebSocket 连接
// =======================

// 连接用于接收弹幕的客户端 WebSocket
function connectClientWebSocket() {
  // 根据当前页面协议选择 ws / wss
  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://'
  const wsUrl = `${protocol}${window.location.host}/api/danmaku/v1/danmaku/${props.roomId}`

  // 已经连接则不重复连接
  if (clientSocketOk.value)
    return

  // 若已有 socket，先关闭
  if (clientSocket.value)
    clientSocket.value.close()

  // 创建新的 WebSocket 实例
  clientSocket.value = new WebSocket(wsUrl)

  // 连接成功
  clientSocket.value.onopen = () => {
    checkConnectionStatus()
  }

  // 接收弹幕消息
  clientSocket.value.onmessage = (event) => {
    const data = JSON.parse(event.data)
    showMessage({ ...data, source: 'client' })
  }

  // 连接关闭，尝试指数退避重连
  clientSocket.value.onclose = () => {
    checkConnectionStatus()
    const reconnectDelay = Math.min(30000, 2 ** Math.min(reconnectAttempts.value, 10) * 1000)
    setTimeout(connectClientWebSocket, reconnectDelay)
    reconnectAttempts.value++
  }

  // 出错时主动关闭，交由 onclose 处理重连
  clientSocket.value.onerror = () => {
    clientSocket.value?.close()
  }
}

// =======================
// 上游 WebSocket 连接
// =======================

// 连接用于发送弹幕与控制指令的上游 WebSocket
function connectUpstreamWebSocket() {
  // 未提供认证 Token 时不连接
  if (!authToken.value)
    return

  // 已连接则不重复连接
  if (upstreamSocketOk.value)
    return

  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://'
  const wsUrl = `${protocol}${window.location.host}/api/danmaku/v1/upstream?token=${authToken.value}`

  // 若已有 socket，先关闭
  if (upstreamSocket.value)
    upstreamSocket.value.close()

  // 创建新的上游 WebSocket
  upstreamSocket.value = new WebSocket(wsUrl)

  // 连接成功
  upstreamSocket.value.onopen = () => {
    checkConnectionStatus()
  }

  // 接收上游返回的消息
  upstreamSocket.value.onmessage = (event) => {
    const data = JSON.parse(event.data)

    // 上游错误信息直接提示
    if (data.error) {
      showMessage({ text: `上游错误: ${data.error}`, source: 'upstream' })
      return
    }

    showMessage({ ...data, source: 'upstream' })
  }

  // 连接关闭后尝试重连（仅在仍有 token 的情况下）
  upstreamSocket.value.onclose = () => {
    checkConnectionStatus()
    if (authToken.value) {
      const reconnectDelay = Math.min(30000, 2 ** reconnectAttempts.value * 1000)
      setTimeout(connectUpstreamWebSocket, reconnectDelay)
      reconnectAttempts.value++
    }
  }

  // 上游连接错误（通常是 token 无效）
  upstreamSocket.value.onerror = () => {
    showMessage({ text: '上游连接失败，请检查Token是否正确', source: 'upstream' })
  }
}

// =======================
// 连接状态统一管理
// =======================

// 根据 socket readyState 统一更新连接状态与系统提示
function checkConnectionStatus() {
  const clientConnected = clientSocket.value && clientSocket.value.readyState === WebSocket.OPEN
  clientSocketOk.value = Boolean(clientConnected)

  const upstreamConnected = upstreamSocket.value && upstreamSocket.value.readyState === WebSocket.OPEN
  upstreamSocketOk.value = Boolean(upstreamConnected)

  // 任一连接成功即认为系统可用
  if (clientConnected || upstreamConnected) {
    if (loading.value) {
      loading.value = false
      reconnectAttempts.value = 0

      const connections = []
      if (clientConnected)
        connections.push('客户端')
      if (upstreamConnected)
        connections.push('上游')

      showMessage({
        text: `元火弹幕姬已连接~ (${connections.join('、')})`,
        source: 'system',
      })
    }
  }
  // 两端都断开
  else {
    loading.value = true
    showMessage({
      text: '元火弹幕姬已断开~',
      source: 'system',
    })
  }
}

// =======================
// WebSocket 统一入口
// =======================

// 初始化并连接客户端与上游 WebSocket
function connectWebSocket() {
  loading.value = true
  connectClientWebSocket()
  connectUpstreamWebSocket()
}

// =======================
// Watchers
// =======================

// 输入变化时清除错误提示
watch(inputValue, () => {
  if (error.value)
    error.value = ''
})

// 同步 props.authKey 到内部 authToken
watch(() => props.authKey, (value) => {
  const normalized = typeof value === 'string' ? value.trim() : ''
  if (normalized !== authToken.value)
    authToken.value = normalized
}, { immediate: true })

// authToken 变化时自动管理上游连接
watch(authToken, () => {
  if (authToken.value) {
    connectUpstreamWebSocket()
  }
  else if (upstreamSocket.value) {
    upstreamSocket.value.close()
  }
})

// =======================
// 生命周期
// =======================

// 组件挂载时建立连接
onMounted(() => {
  connectWebSocket()
})

// 组件卸载时关闭所有连接
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
          <span v-if="message.source" class="message-tag" :class="message.source">
            {{ message.source === 'client' ? '客户端'
              : message.source === 'upstream' ? '上游' : '系统' }}
          </span>
        </header>
        <p class="message-text">{{ message.text }}</p>
      </article>
    </section>

    <section v-if="hasAuthKey" class="opacity-panel">
      <div class="panel-title">全局弹幕控制</div>
      <label class="slider-label">
        <span>弹幕透明度</span>
        <input v-model.number="opacityValue" type="range" min="0" max="100" />
        <span class="slider-value">{{ opacityValue }}%</span>
      </label>
      <button class="primary-btn" :disabled="!canSendOpacity" @click="sendOpacityCommand">
        应用指令
      </button>
    </section>

    <section class="composer">
      <div class="auth-hint" :class="{ ready: hasAuthKey }">
        {{ hasAuthKey ? 'URL key 已加载' : '缺少 URL key，无法连接上游' }}
      </div>
      <input v-model="senderName" class="text-input" type="text" placeholder="输入昵称..." />
      <input
        v-model="inputValue"
        class="text-input"
        type="text"
        :maxlength="MAX_MESSAGE_LENGTH"
        placeholder="输入弹幕..."
        @keydown.enter="sendMessage"
      />
      <button class="primary-btn" :disabled="!canSend" @click="sendMessage">
        发送数据包
      </button>
      <div v-if="error" class="error-text">{{ error }}</div>
    </section>

    <div v-if="inputValue" class="char-counter">
      {{ inputValue.length }}/{{ MAX_MESSAGE_LENGTH }}
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
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.panel-title {
  font-weight: 600;
  color: #f8fafc;
  flex-basis: 100%;
}

.slider-label {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  color: #cbd5f5;
}

.slider-label input[type="range"] {
  flex: 1;
}

.slider-value {
  width: 50px;
  text-align: right;
  font-variant-numeric: tabular-nums;
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
</style>
