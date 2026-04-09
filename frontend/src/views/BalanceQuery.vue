<script setup>
import { ref } from 'vue'

const queryMode = ref('name') // 'name' or 'id'
const username = ref('')
const userId = ref('')
const balances = ref(null)
const loading = ref(false)
const error = ref('')

async function queryBalance() {
  loading.value = true
  error.value = ''
  balances.value = null

  try {
    let url
    if (queryMode.value === 'name') {
      const name = username.value.trim()
      if (!name) return
      url = `/api/danmaku/v1/balance?username=${encodeURIComponent(name)}`
    } else {
      const id = userId.value.trim()
      if (!id) return
      url = `/api/danmaku/v1/balance_by_id?user_id=${encodeURIComponent(id)}`
    }

    const res = await fetch(url)
    if (!res.ok) {
      const detail = await res.json().catch(() => null)
      throw new Error(detail?.detail || `请求失败 (${res.status})`)
    }
    const data = await res.json()
    balances.value = data.balances
  }
  catch (e) {
    error.value = e.message
  }
  finally {
    loading.value = false
  }
}

function checkCanQuery() {
  if (queryMode.value === 'name')
    return username.value.trim().length > 0
  return userId.value.trim().length > 0
}
</script>

<template>
  <div class="balance-page">
    <div class="balance-container">
      <h1 class="title">燕元 / 燕火 余额查询</h1>
      <p class="subtitle">输入用户名或 ID 查询你的燕元和燕火数量</p>

      <div class="mode-tabs">
        <button
          class="mode-tab"
          :class="{ active: queryMode === 'name' }"
          @click="queryMode = 'name'"
        >
          按用户名
        </button>
        <button
          class="mode-tab"
          :class="{ active: queryMode === 'id' }"
          @click="queryMode = 'id'"
        >
          按用户 ID
        </button>
      </div>

      <div class="search-bar">
        <input
          v-if="queryMode === 'name'"
          v-model="username"
          type="text"
          placeholder="请输入用户名"
          class="search-input"
          @keyup.enter="queryBalance"
        >
        <input
          v-else
          v-model="userId"
          type="text"
          placeholder="请输入用户 ID"
          class="search-input"
          @keyup.enter="queryBalance"
        >
        <button
          :disabled="loading || !checkCanQuery()"
          class="search-btn"
          @click="queryBalance"
        >
          {{ loading ? '查询中...' : '查询' }}
        </button>
      </div>

      <div v-if="error" class="error-box">{{ error }}</div>

      <div v-if="balances !== null">
        <div v-if="balances.length === 0" class="empty-hint">
          未找到该用户的记录
        </div>

        <div v-for="item in balances" :key="`${item.room_id}-${item.user_id}`" class="balance-card">
          <div class="room-label">房间：{{ item.room_id }}</div>
          <div class="user-info">{{ item.user_name }} <span class="user-id-text">({{ item.user_id }})</span></div>
          <div class="balance-row">
            <div class="balance-item">
              <div class="balance-value yuan">{{ item.yuan.toFixed(1) }}</div>
              <div class="balance-label">燕元</div>
            </div>
            <div class="divider" />
            <div class="balance-item">
              <div class="balance-value huo">{{ item.huo.toFixed(1) }}</div>
              <div class="balance-label">燕火</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.balance-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #fff8ee 0%, #fff0e0 100%);
  padding: 2rem 1rem;
}

.balance-container {
  max-width: 520px;
  margin: 0 auto;
}

.title {
  font-size: 1.8rem;
  font-weight: 700;
  text-align: center;
  color: #333;
  margin-bottom: 0.4rem;
}

.subtitle {
  text-align: center;
  color: #999;
  margin-bottom: 1.2rem;
  font-size: 0.95rem;
}

.mode-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 1rem;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #ddd;
}

.mode-tab {
  flex: 1;
  padding: 0.5rem 0;
  border: none;
  background: #fff;
  color: #666;
  font-size: 0.95rem;
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}

.mode-tab.active {
  background: #f59e0b;
  color: #fff;
  font-weight: 600;
}

.mode-tab:hover:not(.active) {
  background: #fef3c7;
}

.user-info {
  font-size: 0.9rem;
  color: #555;
  margin-bottom: 0.6rem;
}

.user-id-text {
  color: #aaa;
  font-size: 0.82rem;
}

.search-bar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.search-input {
  flex: 1;
  padding: 0.6rem 1rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.search-input:focus {
  border-color: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.15);
}

.search-btn {
  padding: 0.6rem 1.5rem;
  background: #f59e0b;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.search-btn:hover:not(:disabled) {
  background: #d97706;
}

.search-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-box {
  padding: 0.8rem 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 0.9rem;
  margin-bottom: 1rem;
}

.empty-hint {
  text-align: center;
  color: #bbb;
  padding: 3rem 0;
}

.balance-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  padding: 1.2rem 1.5rem;
  margin-bottom: 1rem;
  border: 1px solid #f3f3f3;
}

.room-label {
  font-size: 0.85rem;
  color: #aaa;
  margin-bottom: 0.8rem;
}

.balance-row {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.balance-item {
  flex: 1;
  text-align: center;
}

.balance-value {
  font-size: 1.6rem;
  font-weight: 700;
}

.balance-value.yuan {
  color: #d97706;
}

.balance-value.huo {
  color: #ef4444;
}

.balance-label {
  font-size: 0.85rem;
  color: #888;
  margin-top: 0.25rem;
}

.divider {
  width: 1px;
  height: 2.5rem;
  background: #eee;
}
</style>
