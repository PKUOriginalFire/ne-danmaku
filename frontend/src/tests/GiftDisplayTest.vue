<template>
    <div>
        <!-- Gift 显示组件 -->
        <GiftDisplay ref="giftRef" />

        <!-- 手动测试按钮 -->
        <button class="btn" @click="sendRandomGift">
            手动发送一个礼物
        </button>
    </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import GiftDisplay from '../components/GiftDisplay.vue'
import { GiftConfig } from '../components/GiftEnum';

const giftRef = ref(null)

let timer = null

/* ===============================
   模拟 WebSocket 推送
================================ */

onMounted(() => {
    timer = setInterval(() => {
        sendRandomGift()
    }, 800)
})

onUnmounted(() => {
    clearInterval(timer)
})

/* ===============================
   模拟礼物发送
================================ */

function sendRandomGift() {
    if (!giftRef.value) return

    const users = ['Alice', 'Bob', 'Charlie', 'David', 'Eve']

    // 你 GiftEnum 里定义的礼物名称
    const giftTypes = Object.keys(GiftConfig)

    const randomUser =
        users[Math.floor(Math.random() * users.length)]

    const randomGift =
        giftTypes[Math.floor(Math.random() * giftTypes.length)]

    // 随机数量，模拟连击
    const quantity = Math.floor(Math.random() * 3) + 1

    giftRef.value.addGift({
        user: randomUser,
        gift_name: randomGift,
        quantity,
        text: `${randomUser} 送出了 ${randomGift}`
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