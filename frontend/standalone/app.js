/**
 * 免构建演示版入口。
 *
 * 与 Vite 工程版（frontend/）共用同一套 REST API，适用于：
 *  - 没装 Node / 不方便 npm install 的演示环境；
 *  - 私有化交付时希望「启动后端即可访问界面」的场景。
 *
 * Vue3 与 ECharts 已本地化到 vendor/，全程不访问任何外部 CDN。
 */
import { createApp, reactive, ref, computed } from 'vue'
import { api, getLocalUser, getToken, setLocalUser, setToken, clearToken } from './api.js'
import {
  DashboardView, OrdersView, ReportWorkView, EquipmentView,
  SpcView, QualityView, InventoryView, ReportsView
} from './views.js'

const state = reactive({
  user: getLocalUser() || { username: '', roles: [], permissions: [] },
  route: (location.hash.replace('#', '') || '/').split('?')[0] || '/'
})

const ROLE_TEXT = { admin: '管理员', line_leader: '班组长', operator: '操作工' }

const LoginView = {
  data() {
    return { form: { username: 'admin', password: 'mes@2026' }, error: '', loading: false }
  },
  methods: {
    async submit() {
      this.error = ''
      this.loading = true
      try {
        const data = await api.login(this.form)
        setToken(data.access_token)
        state.user = {
          username: data.username,
          real_name: data.real_name,
          roles: data.roles,
          permissions: data.permissions
        }
        setLocalUser(state.user)
        location.hash = '/'
        state.route = '/'
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
    pick(username) {
      this.form.username = username
      this.form.password = 'mes@2026'
    }
  },
  template: `
  <div class="login-wrap">
    <form class="login-card" @submit.prevent="submit">
      <h2>离散制造车间生产管理系统</h2>
      <div class="tip">免构建演示版 · 工单→报工→设备→质量→库存</div>
      <div v-if="error" class="alert alert-error">{{ error }}</div>
      <div class="field">
        <label>登录账号</label>
        <input v-model="form.username" autocomplete="username" />
      </div>
      <div class="field">
        <label>密码</label>
        <input v-model="form.password" type="password" autocomplete="current-password" />
      </div>
      <button class="btn" style="width:100%" :disabled="loading">{{ loading ? '登录中…' : '登 录' }}</button>
      <div class="small muted" style="margin-top:14px">
        演示账号（密码 mes@2026）：
        <a href="javascript:void(0)" @click="pick('admin')">admin</a> ·
        <a href="javascript:void(0)" @click="pick('leader')">leader</a> ·
        <a href="javascript:void(0)" @click="pick('worker')">worker</a>
      </div>
    </form>
  </div>
  `
}

const NAVS = [
  { path: '/', label: '车间看板', icon: '◱', comp: DashboardView },
  { path: '/orders', label: '生产工单', icon: '▤', comp: OrdersView },
  { path: '/report-work', label: '工序报工', icon: '✓', comp: ReportWorkView },
  { path: '/equipment', label: '设备状态', icon: '⚙', comp: EquipmentView },
  { path: '/spc', label: 'SPC 控制图', icon: '◔', comp: SpcView },
  { path: '/quality', label: '质量检验', icon: '◈', comp: QualityView },
  { path: '/inventory', label: '库存管理', icon: '▦', comp: InventoryView },
  { path: '/reports', label: '统计报表', icon: '◧', comp: ReportsView }
]

const App = {
  setup() {
    const isLogin = computed(() => Boolean(state.user.username) && Boolean(getToken()))
    const roleText = computed(() =>
      (state.user.roles || []).map((r) => ROLE_TEXT[r] || r).join(' / ') || '-'
    )
    const go = (path) => {
      location.hash = path
      state.route = path
    }
    const logout = () => {
      clearToken()
      state.user = { username: '', roles: [], permissions: [] }
      location.hash = '/'
      state.route = '/'
    }
    return { state, isLogin, roleText, go, logout, NAVS }
  },
  template: `
  <div v-if="!isLogin"><LoginView /></div>
  <div v-else class="app-shell">
    <aside class="app-side">
      <h1>MES 车间系统</h1>
      <div class="sub">离散制造 · 生产管理</div>
      <a v-for="nav in NAVS" :key="nav.path" class="nav-item"
         :class="{ active: state.route === nav.path }"
         href="javascript:void(0)" @click="go(nav.path)">
        {{ nav.icon }} <span>{{ nav.label }}</span>
      </a>
    </aside>
    <div class="app-main">
      <header class="app-header">
        <div class="title">
          {{ (NAVS.find(n => n.path === state.route) || NAVS[0]).label }}
        </div>
        <div class="who">
          {{ state.user.real_name || state.user.username }}
          <span class="tag tag-info" style="margin-left:6px">{{ roleText }}</span>
          <button class="btn plain" style="margin-left:10px" @click="logout">退出</button>
        </div>
      </header>
      <div class="app-content">
        <component :is="(NAVS.find(n => n.path === state.route) || NAVS[0]).comp" />
      </div>
    </div>
  </div>
  `,
  components: { LoginView }
}

window.addEventListener('hashchange', () => {
  state.route = (location.hash.replace('#', '') || '/').split('?')[0] || '/'
})

createApp(App).mount('#app')
