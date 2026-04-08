<template>
    <div class="sc-container">
        <TransitionGroup name="sc" tag="div" @after-enter="handleAfterEnter">
            <div v-for="sc in scDisplayList" :key="sc.id" :data-id="sc.id" class="sc-block"
                :style="{ background: getColor(sc.amount) }">

                <div class="sc-avatar">
                    <img :src="sc.avatar || 'https://placehold.co/100x100/ffffff/111111'" alt="avatar" />
                </div>

                <div class="sc-text-wrap">

                    <div class="sc-header">
                        <strong>{{ sc.user }}</strong>
                        <span class="amount">{{ sc.amount }} 燕火</span>
                    </div>

                    <div class="sc-text">
                        {{ sc.text }}
                    </div>
                </div>

                <div class="sc-progress" :style="{
                    width: sc.progress,
                    transition: 'width ' + sc.ttl + 'ms linear'
                }"></div>
            </div>
        </TransitionGroup>
    </div>
</template>
  
<script setup>
import { ref } from 'vue'

/* ===== 核心状态 ===== */

const scDisplayList = ref([])
const maxDisplay = 5
const scStoreList = ref([])

/* ===== 自动移除逻辑（未改动） ===== */

function autoRemoveSC(sc) {
    if (sc.setAutoRemoved) return
    sc.setAutoRemoved = true

    sc.autoRemoveTimer = setTimeout(() => {
        scDisplayList.value =
            scDisplayList.value.filter(item => item.id !== sc.id)

        if (
            scStoreList.value.length > 0 &&
            scDisplayList.value.length < maxDisplay
        ) {
            const next = scStoreList.value.shift()

            insertByAmount(scDisplayList.value, next)

            autoRemoveSC(next)
        }
    }, sc.ttl)
}

/* ====== insert 逻辑（未改动） ====== */
function insertByAmount(list, sc) {
    const index = list.findIndex(item => item.amount < sc.amount)

    if (index === -1) {
        list.push(sc)
    } else {
        list.splice(index, 0, sc)
    }
}

/* ===== 对外暴露添加 SC 方法 ===== */

function addSC(data) {
    const sc = {
        id: crypto.randomUUID(),
        progress: "0%",
        setAutoRemoved: false,
        autoRemoveTimer: null,
        ...data
    }

    insertByAmount(scDisplayList.value, sc)

    if (scDisplayList.value.length > maxDisplay) {
        const removed = scDisplayList.value.pop()

        if (removed.id === sc.id) {
            insertByAmount(scStoreList.value, removed)
        } else {
            clearTimeout(removed.autoRemoveTimer)
        }
    }
}

/* ===== after-enter 启动动画 ===== */

function handleAfterEnter(el) {
    const id = el.getAttribute('data-id')
    const sc = scDisplayList.value.find(item => item.id === id)

    if (sc) {
        sc.progress = "100%"
        autoRemoveSC(sc)
    }
}

/* ===== 颜色逻辑 ===== */

function getColor(amount) {
    if (amount >= 500) return "linear-gradient(90deg, #ff5f6d, #ffc371)"
    if (amount >= 100) return "linear-gradient(90deg, #2193b0, #6dd5ed)"
    return "linear-gradient(90deg, #56ab2f, #a8e063)"
}

function clearAll() {
    const allItems = [...scDisplayList.value, ...scStoreList.value]
    for (const item of allItems) {
        if (item.autoRemoveTimer) {
            clearTimeout(item.autoRemoveTimer)
        }
    }
    scDisplayList.value = []
    scStoreList.value = []
}

/* ✅ 关键：暴露给父组件 */
defineExpose({
    addSC,
    clearAll,
})
</script>
  
<style scoped>
.sc-container {
    width: 400px;
    top: 20px;
    left: 20px;
    /* transform: translateX(-50%); */
    background: transparent;
    overflow: hidden;
    position: absolute;
}

.sc-block {
    position: relative;
    color: white;
    padding: 12px;
    margin-bottom: 10px;
    border-radius: 8px;
    overflow: hidden;
    z-index: 1;
    display: flex;
}

.sc-avatar {
    width: 50px;
    height: 50px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    margin-right: 12px;
}

.sc-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.sc-text-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.sc-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
}

.sc-progress {
    position: absolute;
    top: 0;
    bottom: 0;
    right: 0;
    width: 0%;
    background: rgba(0, 0, 0, 0.2);
    z-index: -1;
}

.amount {
    font-weight: bold;
}

.sc-text {
    font-size: 14px;
}

.sc-enter-from {
    opacity: 0;
    transform: translateY(-20px);
}

.sc-enter-active {
    transition: all 0.3s ease;
}

.sc-leave-to {
    opacity: 0;
    transform: translateX(100px);
}

.sc-leave-active {
    transition: all 0.3s ease;
}
</style>