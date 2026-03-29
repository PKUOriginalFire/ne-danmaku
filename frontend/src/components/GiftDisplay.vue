<template>
    <div class="gift-container">
        <TransitionGroup
            name="gift"
            tag="div"
            @after-enter="handleAfterEnter"
        >
            <div
                v-for="gift in giftDisplayList"
                :key="gift.id"
                :data-id="gift.id"
                class="gift-item"
                :style="{
                    transform: `scale(${gift.scale})`,
                    background: getColor(gift.level)
                }"
            >
                <div class="gift-avatar">
                    <img :src="gift.avatar || 'https://placeholder.im/100x100/cccccc'" alt="avatar" />
                </div>
                <div class="gift-text-wrap">
                    <div class="gift-user">{{ gift.user }} 投喂</div>
                    <div class="gift-text">{{ gift.name }}</div>
                </div>
                <div class="gift-image">
                    <!-- <img :src="gift.imageURL" alt="gift" /> -->
                    <img :src="'https://placeholder.im/100x100/ff0000'" alt="gift" />
                </div>
                <div class="gift-amount">x{{ gift.amount }}</div>
            </div>
        </TransitionGroup>
    </div>
</template>

<script setup>
import { ref } from 'vue'
import { GiftConfig, isGiftType, formGiftType } from './GiftEnum'

/* ===============================
   核心状态
================================ */

const giftDisplayList = ref([])
const giftStoreList = ref([])

const maxDisplay = 8
const TTL = 8000

/* ===============================
   工具函数
================================ */

function insertByLevel(list, item) {
    const index = list.findIndex(i => i.level < item.level)
    if (index === -1) {
        list.push(item)
    } else {
        list.splice(index, 0, item)
    }
}

function autoRemoveGift(gift) {
    if (gift.setAutoRemoved) return

    gift.setAutoRemoved = true
    gift.autoRemoveTimer = setTimeout(() => {
        removeGift(gift.id)
    }, TTL)
}

function removeGift(id) {
    const index = giftDisplayList.value.findIndex(g => g.id === id)
    if (index === -1) return

    giftDisplayList.value.splice(index, 1)

    if (
        giftStoreList.value.length > 0 &&
        giftDisplayList.value.length < maxDisplay
    ) {
        const next = giftStoreList.value.shift()
        next.setAutoRemoved = false
        insertByLevel(giftDisplayList.value, next)
        autoRemoveGift(next)
    }
}

/* ===============================
   连击放大（核心）
================================ */

function triggerScale(gift) {
    // 叠加放大
    gift.scale += 0.15

    // 最大限制
    if (gift.scale > 1.6) {
        gift.scale = 1.6
    }

    // 下一帧恢复到 1
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            gift.scale = 1
        })
    })
}

function refreshGift(existing, newGift) {
    existing.amount += newGift.amount
    existing.text = newGift.text

    triggerScale(existing)

    clearTimeout(existing.autoRemoveTimer)
    existing.setAutoRemoved = false
    autoRemoveGift(existing)
}

/* ===============================
   添加礼物
================================ */

function addGift(data) {
    if (!isGiftType(data.gift_name)) {
        console.warn('未知礼物类型:', data.gift_name)
        return
    }

    const giftType = formGiftType(data.gift_name)
    const config = GiftConfig[giftType]

    const gift = {
        id: crypto.randomUUID(),
        setAutoRemoved: false,
        autoRemoveTimer: null,
        scale: 1,
        ...data,
        name: config.name,
        amount: data.quantity,
        cost: data.cost | data.quantity * config.cost,
        giftType: giftType,
        level: config.level,
        imageURL: config.imageURL,
    }

    const existing = giftDisplayList.value.find(
        item =>
            item.user === gift.user &&
            item.giftType === gift.giftType
    )

    if (existing) {
        refreshGift(existing, gift)
        return
    }

    if (giftDisplayList.value.length < maxDisplay) {
        insertByLevel(giftDisplayList.value, gift)
        return
    }

    const lowest = giftDisplayList.value[giftDisplayList.value.length - 1]

    if (gift.level > lowest.level) {
        giftDisplayList.value.pop()
        clearTimeout(lowest.autoRemoveTimer)
        giftStoreList.value.push(lowest)
        insertByLevel(giftDisplayList.value, gift)
    } else {
        insertByLevel(giftStoreList.value, gift)
    }
}

/* ===============================
   动画回调
================================ */

function handleAfterEnter(el) {
    const id = el.getAttribute('data-id')
    const gift = giftDisplayList.value.find(item => item.id === id)

    if (gift) {
        autoRemoveGift(gift)
    }
}

function getColor(level) {
    // from 1 to 5, linear gradient
    switch (level) {
        case 5:
            return "linear-gradient(90deg, #ffc371, #ff5f6d)"
        case 4:
            return "linear-gradient(90deg, #24c6dc, #514a9d)"
        case 3:
            return "linear-gradient(90deg, #f7971e, #ffd200)"
        case 2:
            return "linear-gradient(90deg, #56ab2f, #a8e063)"
        default:
            return "linear-gradient(90deg, #333, #555)"
    }
}

/* =============================== */

defineExpose({
    addGift
})
</script>

<style scoped>
.gift-container {
    width: 400px;
    position: absolute;
    top: 20px;
    right: 20px;
}

.gift-item {
    background: #333;
    color: white;
    padding: 5px;
    margin-bottom: 10px;
    border-radius: 50px;
    display: flex;
    position: relative;
    align-items: center;

    /* 关键：只用 transition */
    transition: transform 0.25s cubic-bezier(.2,1.6,.4,1);
}

.gift-text-wrap {
    text-shadow: 0 0 2px rgba(0,0,0,0.5);
}

.gift-avatar {
    width: 50px;
    height: 50px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    margin-right: 12px;
}

.gift-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.gift-image {
    width: 50px;
    height: 50px;
    position: absolute;
    right: 100px;
}

.gift-image img {
    width: 100%;
    height: 100%;
    object-fit: contain;
}

.gift-amount {
    position: absolute;
    right: 20px;
    bottom: 10px;
    font-size: 32px;
    font-weight: bold;
}

/* 入场动画 */
.gift-enter-from {
    opacity: 0;
    transform: translateX(-50px);
}

.gift-enter-active {
    transition: all 0.3s ease;
}

.gift-leave-to {
    opacity: 0;
    transform: translateX(50px);
}

.gift-leave-active {
    transition: all 0.3s ease;
}
</style>