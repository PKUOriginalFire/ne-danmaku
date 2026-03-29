<template>
    <div>
        <!-- SC 显示组件 -->
        <SuperChatDisplay ref="scRef" />

        <!-- 手动测试按钮（可选） -->
        <button class="btn" @click="sendRandomSC">
            手动发送一条 SC
        </button>
    </div>
</template>
  
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import SuperChatDisplay from '../components/SuperChatDisplay.vue'

const scRef = ref(null)

let timer = null

/* ===== 原来的模拟 WS 逻辑搬到这里 ===== */

onMounted(() => {
    timer = setInterval(() => {
        sendRandomSC()
    }, 1000)
})

onUnmounted(() => {
    clearInterval(timer)
})

function sendRandomSC() {
    if (!scRef.value) return

    const amountList = [30, 50, 100, 500]
    const amount =
        amountList[Math.floor(Math.random() * amountList.length)]

    const ttl = amount * 100

    scRef.value.addSC({
        user: "User" + Math.floor(Math.random() * 100),
        amount,
        text: "这是一条测试 SC",
        ttl
    })
}
</script>
  
<style scoped>
.btn {
    position: fixed;
    bottom: 20px;
    left: 20px;
    padding: 8px 12px;
    border: none;
    border-radius: 6px;
    background: #333;
    color: white;
    cursor: pointer;
}
</style>