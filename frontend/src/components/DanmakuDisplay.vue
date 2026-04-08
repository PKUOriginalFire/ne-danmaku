<script setup>
import Danmaku from 'danmaku'
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { z } from 'zod'
import { AssetManager, AssetReadyQueue } from './ResourceManager'

import SuperChatDisplay from './SuperChatDisplay.vue'
import GiftDisplay from './GiftDisplay.vue'

const props = defineProps({
  roomId: {
    type: String,
    required: true,
  },
})

const containerRef = ref(null)
const loading = ref(true)
const danmaku = ref(null)
const socket = ref(null)
const reconnectAttempts = ref(0)
const overlayOpacity = ref(1)
const scRef = ref(null)
const giftRef = ref(null)
const danmakuResizeCleanup = ref(null)
const roomSettings = ref({
  overlay_opacity: 100,
  enable_emoji: true,
  enable_superchat: true,
  enable_gift: true,
  bind_position: true,
})

const configSchema = z.object({
  defaultColor: z.string().catch('white'),
  defaultSize: z.coerce.number().catch(40),
  speed: z.coerce.number().catch(144),
  font: z.string().catch('sans-serif'),
})

function getConfig() {
  const params = new URLSearchParams(window.location.search)
  return configSchema.parse(Object.fromEntries(params))
}

const assetManager = new AssetManager()
const assetReadyQueue = new AssetReadyQueue(assetManager, {
  maxConcurrent: 6,
})

const emoteMapping = ref({})
const EMOTE_PATTERN = /^[\[【](.+?)[\]】]$/

async function loadEmoteMapping() {
  try {
    const resp = await fetch('/api/danmaku/v1/emotes')
    if (resp.ok) {
      emoteMapping.value = await resp.json()
    }
  }
  catch (e) {
    console.warn('Failed to load emote mapping', e)
  }
}

function applyRoomSettings(settings) {
  roomSettings.value = {
    overlay_opacity: Number(settings?.overlay_opacity ?? 100),
    enable_emoji: Boolean(settings?.enable_emoji ?? true),
    enable_superchat: Boolean(settings?.enable_superchat ?? true),
    enable_gift: Boolean(settings?.enable_gift ?? true),
    bind_position: Boolean(settings?.bind_position ?? true),
  }
  const value = Math.max(0, Math.min(100, roomSettings.value.overlay_opacity))
  overlayOpacity.value = value / 100
}

function handleEmoji(msg) {
  if (!roomSettings.value.enable_emoji)
    return
  const task = {
    id: msg.emote_url,
    resourceKeys: [`/api/emoji/${msg.emote_url}`],
    payload: msg,
    onReady: (payload) => {
      const img = new Image()
      img.src = `/api/emoji/${payload.emote_url}`
      emitEmoji(payload, img)
    },
  }
  assetReadyQueue.enqueue(task)
}

function emitEmoji(msg, img) {
  const config = getConfig()
  const size = msg.size ?? config.defaultSize

  const payload = {
    render: () => {
      img.style.width = `${2 * size}px`
      img.style.height = `${2 * size}px`
      img.style.display = 'block'
      img.style.objectFit = 'contain'
      img.style.opacity = overlayOpacity.value ?? 1
      return img
    },
  }

  danmaku.value.emit(payload)
}

function emitCustomEmote(emoteUrl, msg) {
  if (!danmaku.value)
    return
  const config = getConfig()
  const size = msg.size ?? config.defaultSize
  const img = new Image()
  img.src = emoteUrl
  const payload = {
    render: () => {
      img.style.width = `${2 * size}px`
      img.style.height = `${2 * size}px`
      img.style.display = 'block'
      img.style.objectFit = 'contain'
      img.style.opacity = overlayOpacity.value ?? 1
      return img
    },
  }
  danmaku.value.emit(payload)
}

function handleSC(msg) {
  if (!roomSettings.value.enable_superchat)
    return
  const task = {
    id: msg.avatar_url,
    resourceKeys: [`/api/emoji/${msg.avatar_url}`],
    payload: msg,
    onReady: emitSC,
  }
  assetReadyQueue.enqueue(task)
}

function emitSC(msg) {
  scRef.value.addSC({
    id: msg.sender + msg.text + new Date().getTime(),
    user: msg.sender,
    amount: msg.cost,
    text: msg.text,
    ttl: msg.duration * 1000,
    avatar: `/api/emoji/${msg.avatar_url}`,
  })
}

function handleGift(msg) {
  if (!roomSettings.value.enable_gift)
    return
  const task = {
    id: msg.avatar_url,
    resourceKeys: [`/api/emoji/${msg.avatar_url}`],
    payload: msg,
    onReady: emitGift,
  }
  assetReadyQueue.enqueue(task)
}

function emitGift(msg) {
  giftRef.value.addGift({
    id: msg.sender + msg.gift_name + new Date().getTime(),
    user: msg.sender,
    gift_name: msg.gift_name,
    quantity: msg.quantity,
    cost: msg.cost,
    image_url: msg.image_url,
    avatar: `/api/emoji/${msg.avatar_url}`,
  })
}

function resolveMode(msg) {
  const incoming = msg.position
  if (!roomSettings.value.bind_position)
    return 'rtl'
  if (incoming === 'top' || incoming === 'bottom' || incoming === 'rtl')
    return incoming
  if (incoming === 'scroll')
    return 'rtl'
  return 'rtl'
}

function sendMessage(msg) {
  if (!danmaku.value)
    return

  const config = getConfig()
  const color = msg.color ?? config.defaultColor
  const size = msg.size ?? config.defaultSize
  const mode = resolveMode(msg)
  const type = msg.type ?? 'plain'

  if (type === 'plain') {
    // Check for text-to-emote conversion: [emote_name] or 【emote_name】
    const emoteMatch = msg.text?.match(EMOTE_PATTERN)
    if (emoteMatch) {
      const emoteName = emoteMatch[1]
      const emoteUrl = emoteMapping.value[emoteName]
      if (emoteUrl) {
        emitCustomEmote(emoteUrl, msg)
        return
      }
    }

    const payload = {
      mode,
      text: msg.text,
      style: {
        fontFamily: config.font,
        fontSize: `${size}px`,
        fontWeight: 'bold',
        color,
        textShadow: '#000 1px 0px 1px, #000 0px 1px 1px, #000 0px -1px 1px, #000 -1px 0px 1px',
        opacity: overlayOpacity.value ?? 1,
      },
    }
    danmaku.value.emit(payload)
  }
  else if (type === 'emote') {
    handleEmoji(msg)
  }
  else if (type === 'superchat') {
    handleSC(msg)
  }
  else if (type === 'gift') {
    handleGift(msg)
  }
}

function clearAllOverlays() {
  scRef.value?.clearAll?.()
  giftRef.value?.clearAll?.()
  danmakuResizeCleanup.value?.()
  danmakuResizeCleanup.value = null
  danmaku.value?.destroy()
  danmaku.value = null
  initDanmaku()
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://'
  const wsUrl = `${protocol}${window.location.host}/api/danmaku/v1/danmaku/${props.roomId}`

  socket.value = new WebSocket(wsUrl)
  socket.value.onopen = () => {
    reconnectAttempts.value = 0
    loading.value = false
    sendMessage({ text: '元火弹幕姬已连接~' })
  }
  socket.value.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data?.type === 'settings' && data?.settings) {
      applyRoomSettings(data.settings)
      return
    }
    if (data?.type === 'control' && data?.action === 'clear_all') {
      clearAllOverlays()
      return
    }
    sendMessage(data)
  }
  socket.value.onclose = () => {
    loading.value = true
    sendMessage({ text: '元火弹幕姬已断开~' })
    const reconnectDelay = Math.min(30000, 2 ** reconnectAttempts.value * 1000)
    setTimeout(connectWebSocket, reconnectDelay)
    reconnectAttempts.value++
  }
  socket.value.onerror = () => {
    socket.value.close()
  }
}

function initDanmaku() {
  if (!containerRef.value)
    return

  danmakuResizeCleanup.value?.()
  danmakuResizeCleanup.value = null
  danmaku.value?.destroy()
  danmaku.value = null

  const config = getConfig()
  danmaku.value = new Danmaku({
    container: containerRef.value,
    engine: 'dom',
    speed: config.speed,
  })
  danmaku.value.show()

  const handleResize = () => danmaku.value?.resize()
  window.addEventListener('resize', handleResize)
  danmakuResizeCleanup.value = () => {
    window.removeEventListener('resize', handleResize)
  }
}

onMounted(() => {
  initDanmaku()
  loadEmoteMapping()
  connectWebSocket()
})

onUnmounted(() => {
  danmakuResizeCleanup.value?.()
  danmakuResizeCleanup.value = null
  socket.value?.close()
  danmaku.value?.destroy()
  danmaku.value = null
})

watch(() => props.roomId, () => {
  socket.value?.close()
  applyRoomSettings({})
  connectWebSocket()
})
</script>

<template>
  <div ref="containerRef" class="danmaku-container">
    <div v-if="loading" class="danmaku-loading">
      <div class="spinner" />
      <p>加载中...</p>
    </div>
  </div>
  <SuperChatDisplay ref="scRef" />
  <GiftDisplay ref="giftRef" />
</template>

<style scoped>
.danmaku-container {
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
  background: transparent;
}

.danmaku-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: linear-gradient(180deg, rgba(3, 7, 18, 0.85), rgba(15, 23, 42, 0.85));
  color: #94a3b8;
  text-align: center;
  letter-spacing: 0.05em;
}

.spinner {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  border: 4px solid rgba(148, 163, 184, 0.3);
  border-top-color: #38bdf8;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
