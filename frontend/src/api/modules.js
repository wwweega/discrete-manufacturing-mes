/** 按后端模块划分的接口清单，和 Swagger 的 tag 一一对应。 */
import { http } from './request'

export const authApi = {
  login: (data) => http.post('/api/v1/auth/login', data),
  me: () => http.get('/api/v1/auth/me')
}

export const masterApi = {
  all: () => http.get('/api/v1/master'),
  health: () => http.get('/api/v1/master/health')
}

export const orderApi = {
  list: (params) => http.get('/api/v1/orders', params),
  create: (data) => http.post('/api/v1/orders', data),
  detail: (id) => http.get(`/api/v1/orders/${id}`),
  transitions: (id) => http.get(`/api/v1/orders/${id}/allowed-transitions`),
  transition: (id, data) => http.post(`/api/v1/orders/${id}/transition`, data),
  report: (id, data, idempotencyKey) =>
    http.post(`/api/v1/orders/${id}/report`, data, {
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}
    }),
  statusMachine: () => http.get('/api/v1/orders/status-machine')
}

export const qualityApi = {
  tasks: (params) => http.get('/api/v1/quality/tasks', params),
  createTask: (data) => http.post('/api/v1/quality/tasks', data),
  transition: (id, data) => http.post(`/api/v1/quality/tasks/${id}/transition`, data),
  addRecord: (id, data) => http.post(`/api/v1/quality/tasks/${id}/records`, data),
  rules: () => http.get('/api/v1/quality/spc/rules'),
  addSubgroup: (data) => http.post('/api/v1/quality/spc/subgroups', data),
  chart: (productId, operationCode, tail = 30) =>
    http.get(`/api/v1/quality/spc/chart/${productId}/${operationCode}`, { tail }),
  analyze: (data) => http.post('/api/v1/quality/spc/analyze', data)
}

export const inventoryApi = {
  stock: (params) => http.get('/api/v1/inventory', params),
  transactions: (params) => http.get('/api/v1/inventory/transactions', params),
  issue: (data) => http.post('/api/v1/inventory/issue', data),
  ret: (data) => http.post('/api/v1/inventory/return', data),
  adjust: (data) => http.post('/api/v1/inventory/adjust', data)
}

export const dashboardApi = {
  overview: () => http.get('/api/v1/dashboard'),
  distribution: () => http.get('/api/v1/dashboard/status-distribution'),
  recentReports: (limit = 8) => http.get('/api/v1/dashboard/recent-reports', { limit }),
  outputTrend: (days = 7) => http.get('/api/v1/dashboard/output-trend', { days }),
  realtime: () => http.get('/api/v1/dashboard/realtime'),
  equipmentSummary: (sinceHours = 24) =>
    http.get('/api/v1/dashboard/equipment-summary', { since_hours: sinceHours }),
  collectOnce: () => http.post('/api/v1/dashboard/gateway/collect'),
  gatewayStatus: () => http.get('/api/v1/dashboard/gateway/status')
}

export const reportApi = {
  catalog: () => http.get('/api/v1/reports'),
  query: (code, params) => http.get(`/api/v1/reports/${code}`, params)
}
