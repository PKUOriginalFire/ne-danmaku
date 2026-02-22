<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import DanmakuDisplay from '../components/DanmakuDisplay.vue'

const route = useRoute()
const roomId = computed(() => route.params.roomId ?? 'default')
</script>

<template>
  <section class="danmaku-view">
    <DanmakuDisplay :room-id="roomId" />
  </section>
</template>

<style scoped>
.danmaku-view {
  width: 100vw;
  height: 100vh;
  background: #000;
  overflow: hidden;
}
</style>
