import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '../api/request'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '车间看板' } },
  { path: '/orders', name: 'orders', component: () => import('../views/OrdersView.vue'), meta: { title: '生产工单' } },
  { path: '/reports-work', name: 'report-work', component: () => import('../views/ReportWorkView.vue'), meta: { title: '工序报工' } },
  { path: '/equipment', name: 'equipment', component: () => import('../views/EquipmentView.vue'), meta: { title: '设备状态' } },
  { path: '/spc', name: 'spc', component: () => import('../views/SpcView.vue'), meta: { title: 'SPC 控制图' } },
  { path: '/quality', name: 'quality', component: () => import('../views/QualityView.vue'), meta: { title: '质量检验' } },
  { path: '/inventory', name: 'inventory', component: () => import('../views/InventoryView.vue'), meta: { title: '库存管理' } },
  { path: '/reports', name: 'reports', component: () => import('../views/ReportsView.vue'), meta: { title: '统计报表' } },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach((to) => {
  if (!to.meta.public && !getToken()) {
    return { name: 'login' }
  }
  return true
})

export default router
