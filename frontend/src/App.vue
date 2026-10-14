<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './store'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const navs = [
  { name: 'dashboard', label: '车间看板', icon: '◱' },
  { name: 'orders', label: '生产工单', icon: '▤' },
  { name: 'report-work', label: '工序报工', icon: '✓' },
  { name: 'equipment', label: '设备状态', icon: '⚙' },
  { name: 'spc', label: 'SPC 控制图', icon: '◔' },
  { name: 'quality', label: '质量检验', icon: '◈' },
  { name: 'inventory', label: '库存管理', icon: '▦' },
  { name: 'reports', label: '统计报表', icon: '◧' }
]

const title = computed(() => route.meta.title || '离散制造车间生产管理系统')

const logout = () => {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1>MES 车间系统</h1>
      <div class="sub">离散制造 · 生产管理</div>
      <router-link
        v-for="nav in navs"
        :key="nav.name"
        class="nav-item"
        :class="{ active: route.name === nav.name }"
        :to="{ name: nav.name }"
      >
        {{ nav.icon }} <span>{{ nav.label }}</span>
      </router-link>
    </aside>

    <div class="app-main">
      <header class="app-header">
        <div class="title">{{ title }}</div>
        <div class="who">
          {{ auth.user.real_name || auth.user.username }}
          <span class="tag tag-info" style="margin-left: 6px">{{ auth.roleText }}</span>
          <button class="btn plain" style="margin-left: 10px" @click="logout">退出</button>
        </div>
      </header>
      <div class="app-content">
        <router-view />
      </div>
    </div>
  </div>
</template>
