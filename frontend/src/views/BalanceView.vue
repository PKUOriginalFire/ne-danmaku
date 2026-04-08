<template>
    <div class="balance-page">
        <div class="card">
            <h2>查询余额</h2>

            <div class="form-row">
                <label for="qq">QQ号</label>
                <input id="qq" v-model.trim="qq" type="text" placeholder="请输入QQ号" @keyup.enter="fetchBalance" />
            </div>

            <button :disabled="loading || !qq" @click="fetchBalance">
                {{ loading ? "查询中..." : "查询余额" }}
            </button>

            <p v-if="error" class="error">{{ error }}</p>

            <div v-if="result" class="result">
                <div class="result-row">
                    <span>群组：</span>
                    <strong>{{ result.group }}</strong>
                </div>
                <div class="result-row">
                    <span>QQ号：</span>
                    <strong>{{ result.user_id }}</strong>
                </div>
                <div class="result-row">
                    <span>元：</span>
                    <strong>{{ result.yuan }}</strong>
                </div>
                <div class="result-row">
                    <span>火：</span>
                    <strong>{{ result.huo }}</strong>
                </div>
            </div>
        </div>
    </div>
</template>
  
<script setup lang="ts">
import { ref, computed } from "vue";
import { useRoute } from 'vue-router'

interface BalanceResponse {
    group: string;
    user_id: string;
    yuan: number;
    huo: number;
}

const route = useRoute()

// 这里改成你的实际 group
const group = computed(() => String(route.params.roomId ?? '弹幕群'))

const qq = ref("");
const loading = ref(false);
const error = ref("");
const result = ref<BalanceResponse | null>(null);

async function fetchBalance() {
    if (!qq.value) {
        error.value = "请输入QQ号";
        result.value = null;
        return;
    }

    if (!group.value) {
        error.value = "未指定群组";
        result.value = null;
        return;
    }

    loading.value = true;
    error.value = "";
    result.value = null;

    try {
        const url = `/api/danmaku/v1/${encodeURIComponent(group.value)}/${encodeURIComponent(qq.value)}`;

        const resp = await fetch(url, {
            method: "GET",
        });

        if (resp.status === 404) {
            error.value = "未找到该用户，请确认QQ号正确输入";
            return;
        }

        if (!resp.ok) {
            error.value = `请求失败：HTTP ${resp.status}`;
            return;
        }

        const data = (await resp.json()) as BalanceResponse;
        result.value = data;
    } catch (e) {
        console.error(e);
        error.value = "网络错误或后端不可达";
    } finally {
        loading.value = false;
    }
}
</script>
  
<style scoped>
.balance-page {
    min-height: 100vh;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 40px 16px;
    background: #f5f7fb;
}

.card {
    width: 100%;
    max-width: 420px;
    background: #fff;
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}

h2 {
    margin: 0 0 20px;
    font-size: 22px;
    font-weight: 700;
    color: #222;
}

.form-row {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 16px;
}

label {
    font-size: 14px;
    color: #555;
}

input {
    height: 40px;
    padding: 0 12px;
    border: 1px solid #dcdfe6;
    border-radius: 8px;
    font-size: 14px;
    outline: none;
}

input:focus {
    border-color: #409eff;
}

button {
    width: 100%;
    height: 40px;
    border: none;
    border-radius: 8px;
    background: #409eff;
    color: #fff;
    font-size: 14px;
    cursor: pointer;
}

button:disabled {
    background: #a0cfff;
    cursor: not-allowed;
}

.error {
    margin-top: 14px;
    color: #d93025;
    font-size: 14px;
}

.result {
    margin-top: 20px;
    padding: 16px;
    border-radius: 8px;
    background: #f8fafc;
    border: 1px solid #e5e7eb;
}

.result-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    font-size: 15px;
    color: #333;
}
</style>