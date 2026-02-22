<script setup>
// 引入第三方弹幕库
import Danmaku from 'danmaku'
// 引入 Vue 组合式 API
import { onMounted, onUnmounted, ref, watch } from 'vue'
// 引入 zod，用于配置参数校验与默认值处理
import { z } from 'zod'
// 引入图片缓存系统
import { AssetManager, AssetReadyQueue } from './ResourceManager'

import SuperChatDisplay from './SuperChatDisplay.vue';
import GiftDisplay from './GiftDisplay.vue';

// 定义组件 props：房间 ID，用于区分弹幕房间
const props = defineProps({
  roomId: {
    type: String,
    required: true,
  },
})

// 弹幕容器 DOM 引用
const containerRef = ref(null)
// 是否处于加载/重连状态
const loading = ref(true)
// Danmaku 实例引用
const danmaku = ref(null)
// WebSocket 实例引用
const socket = ref(null)
// 当前重连次数
const reconnectAttempts = ref(0)
// 弹幕整体透明度（0~1）
const overlayOpacity = ref(1)
// SC 显示组件引用 
const scRef = ref(null)
// 礼物显示组件引用
const giftRef = ref(null)

// URL 参数配置的校验与默认值定义
const configSchema = z.object({
  // 默认弹幕颜色
  defaultColor: z.string().catch('white'),
  // 默认字体大小（px）
  defaultSize: z.coerce.number().catch(40),
  // 弹幕速度
  speed: z.coerce.number().catch(144),
  // 字体族
  font: z.string().catch('sans-serif'),
})

// 从 URL query 中读取配置并解析为合法配置对象
function getConfig() {
  const params = new URLSearchParams(window.location.search)
  return configSchema.parse(Object.fromEntries(params))
}

const assetManager = new AssetManager()
const assetReadyQueue = new AssetReadyQueue(assetManager, {
  maxConcurrent: 6
})


function handleEmoji(msg) {
  const task = {
    id: msg.emote_url,
    resourceKeys: [`/api/emoji/${msg.emote_url}`],
    payload: msg,
    onReady: (payload) => {
      const img = new Image()
      img.src = `/api/emoji/${payload.emote_url}`
      emitEmoji(payload, img)
    }
  }
  assetReadyQueue.enqueue(task)
}

function emitEmoji(msg, img) {
  const config = getConfig()
  const size = msg.size ?? config.defaultSize

  const payload = {
    render: function () {
      img.style.width = `${2 * size}px`
      img.style.height = `${2 * size}px`
      img.style.display = "block"   // 防止 inline 抖动
      img.style.objectFit = "contain"
      img.style.opacity = overlayOpacity.value ?? 1
      return img
    }
  }

  danmaku.value.emit(payload)
}

function handleSC(msg) {
  const task = {
    id: msg.avatar_url,
    resourceKeys: [`/api/emoji/${msg.avatar_url}`],
    payload: msg,
    onReady: emitSC
  }
  assetReadyQueue.enqueue(task)
}

function emitSC(msg) {
  scRef.value.addSC({
    id: msg.sender+msg.text+new Date().getTime(),
    user: msg.sender,
    amount: msg.cost,
    text: msg.text,
    ttl: msg.duration,
    avatar: `/api/emoji/${msg.avatar_url}`
  })
}

function handleGift(msg) {
  const task = {
    id: msg.avatar_url,
    resourceKeys: [`/api/emoji/${msg.avatar_url}`],
    payload: msg,
    onReady: emitGift
  }
  assetReadyQueue.enqueue(task)
}

function emitGift(msg) {
  giftRef.value.addGift({
    id: msg.sender+msg.gift_name+new Date().getTime(),
    user: msg.sender,
    gift_name: msg.gift_name,
    quantity: msg.quantity,
    cost: msg.cost,
    avatar: `/api/emoji/${msg.avatar_url}`,
  })
}

// 向 Danmaku 实例发送一条弹幕
function sendMessage(msg) {
  // 未初始化弹幕实例时直接返回
  if (!danmaku.value)
    return

  // 读取当前配置
  const config = getConfig()
  // 使用消息自带颜色或默认颜色
  const color = msg.color ?? config.defaultColor
  // 使用消息自带字号或默认字号
  const size = msg.size ?? config.defaultSize
  // 使用消息自带pos或默认pos，默认为滚动弹幕
  const mode = msg.position ?? 'rtl'

  const type = msg.type ?? 'plain'

  if (type === 'plain') {
    // 构造弹幕负载
    const payload = {
      mode: mode,
      text: msg.text,
      style: {
        fontFamily: config.font,
        fontSize: `${size}px`,
        fontWeight: 'bold',
        color,
        // 描边阴影，增强可读性
        textShadow: '#000 1px 0px 1px, #000 0px 1px 1px, #000 0px -1px 1px, #000 -1px 0px 1px',
        // 使用当前全局透明度
        opacity: overlayOpacity.value ?? 1,
      },
    }

    // 发射弹幕
    danmaku.value.emit(payload)
  } else if (type === 'emote') {
    // 处理表情弹幕
    handleEmoji(msg)
  } else if (type === 'superchat') {
    // 处理 SC 弹幕
    handleSC(msg)
  } else if (type === 'gift') {
    // 处理礼物弹幕
    handleGift(msg)
  }

}

// 建立 WebSocket 连接
function connectWebSocket() {
  // 根据当前协议选择 ws / wss
  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://'
  // 拼接弹幕 WebSocket 地址
  const wsUrl = `${protocol}${window.location.host}/api/danmaku/v1/danmaku/${props.roomId}`

  // 创建 WebSocket 实例
  socket.value = new WebSocket(wsUrl)

  // 连接成功回调
  socket.value.onopen = () => {
    reconnectAttempts.value = 0
    loading.value = false
    // 发送系统提示弹幕
    sendMessage({ text: '元火弹幕姬已连接~' })
  }

  // 接收消息回调
  socket.value.onmessage = (event) => {
    const data = JSON.parse(event.data)

    // 控制消息：设置弹幕透明度
    if (data?.control?.type === 'setOpacity') {
      const value = Math.max(0, Math.min(100, Number(data.control.value) || 0))
      overlayOpacity.value = value / 100
      return
    }

    // 普通弹幕消息
    sendMessage(data)
  }

  // 连接关闭回调
  socket.value.onclose = () => {
    loading.value = true
    // 发送断开提示弹幕
    sendMessage({ text: '元火弹幕姬已断开~' })

    // 指数退避重连，最大 30 秒
    const reconnectDelay = Math.min(30000, 2 ** reconnectAttempts.value * 1000)
    setTimeout(connectWebSocket, reconnectDelay)
    reconnectAttempts.value++
  }

  // 发生错误时主动关闭连接，触发 onclose 重连逻辑
  socket.value.onerror = () => {
    socket.value.close()
  }
}

// 初始化 Danmaku 实例
function initDanmaku() {
  // 容器未挂载时直接返回
  if (!containerRef.value)
    return

  // 读取配置
  const config = getConfig()
  // 创建 Danmaku 实例
  danmaku.value = new Danmaku({
    container: containerRef.value,
    engine: 'dom',
    speed: config.speed,
  })
  // 显示弹幕
  danmaku.value.show()

  // 窗口尺寸变化时同步调整弹幕尺寸
  const handleResize = () => danmaku.value?.resize()
  window.addEventListener('resize', handleResize)

  // 返回清理函数
  return () => {
    window.removeEventListener('resize', handleResize)
  }
}

// 组件挂载时执行
onMounted(() => {
  // 初始化弹幕并获取清理函数
  const cleanup = initDanmaku()
  // 建立 WebSocket 连接
  connectWebSocket()

  // 组件卸载时清理资源
  onUnmounted(() => {
    cleanup?.()
    socket.value?.close()
    danmaku.value?.destroy()
  })
})

// 监听房间 ID 变化，切换弹幕房间
watch(() => props.roomId, () => {
  socket.value?.close()
  overlayOpacity.value = 1
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
