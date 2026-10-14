<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api/modules'
import { setToken } from '../api/request'
import { useAuthStore } from '../store'

const router = useRouter()
const auth = useAuthStore()

const form = ref({ username: 'admin', password: 'mes@2026' })
const error = ref('')
const loading = ref(false)

const demoAccounts = [
  { username: 'admin', label: '管理员 admin' },
  { username: 'leader', label: '班组长 leader' },
  { username: 'worker', label: '操作工 worker' }
]

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const data = await authApi.login(form.value)
    setToken(data.access_token)
    await auth.login(form.value.username, form.value.password)
    router.push({ name: 'dashboard' })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <form class="login-card" @submit.prevent="submit">
      <h2>离散制造车间生产管理系统</h2>
      <div class="tip">离散制造 MES · 覆盖工单→报工→设备→质量→库存</div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <div class="field">
        <label>登录账号</label>
        <input v-model="form.username" placeholder="admin / leader / worker" autocomplete="username" />
      </div>
      <div class="field">
        <label>密码</label>
        <input v-model="form.password" type="password" placeholder="mes@2026" autocomplete="current-password" />
      </div>

      <button class="btn" style="width: 100%" :disabled="loading">
        {{ loading ? '登录中…' : '登 录' }}
      </button>

      <div class="small muted" style="margin-top: 14px">
        演示账号（密码统一 <code>mes@2026</code>）：
        <div style="margin-top: 4px">
          <span v-for="acc in demoAccounts" :key="acc.username" style="margin-right: 10px">
            <a href="javascript:void(0)" @click="form.username = acc.username; form.password = 'mes@2026'">
              {{ acc.label }}
            </a>
          </span>
        </div>
      </div>
    </form>
  </div>
</template>
