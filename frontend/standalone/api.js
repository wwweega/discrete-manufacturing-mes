/** 免构建演示版：统一请求封装（与 Vite 版 request.js 语义一致）。 */

const TOKEN_KEY = 'mes_token'
const USER_KEY = 'mes_user'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}
export const getLocalUser = () => {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || '{}')
  } catch {
    return {}
  }
}
export const setLocalUser = (u) => localStorage.setItem(USER_KEY, JSON.stringify(u))

async function request(url, { method = 'GET', params, body, headers = {} } = {}) {
  let finalUrl = url.startsWith('/') ? url : `/${url}`
  if (params) {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') search.append(k, v)
    })
    const qs = search.toString()
    if (qs) finalUrl += `?${qs}`
  }
  const res = await fetch(finalUrl, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      ...headers
    },
    ...(body && method !== 'GET' ? { body: JSON.stringify(body) } : {})
  })
  const payload = await res.json().catch(() => ({ code: res.status, msg: '响应解析失败' }))
  if (res.status === 401 || payload.code === 401) {
    clearToken()
    throw new Error(payload.msg || '登录已失效')
  }
  if (!res.ok || payload.code !== 0) {
    throw new Error(payload.msg || `请求失败（${payload.code}）`)
  }
  return payload.data
}

export const api = {
  login: (data) => request('/api/v1/auth/login', { method: 'POST', body: data }),
  master: () => request('/api/v1/master'),
  orders: (params) => request('/api/v1/orders', { params }),
  createOrder: (data) => request('/api/v1/orders', { method: 'POST', body: data }),
  orderDetail: (id) => request(`/api/v1/orders/${id}`),
  transition: (id, data) => request(`/api/v1/orders/${id}/transition`, { method: 'POST', body: data }),
  report: (id, data, key) =>
    request(`/api/v1/orders/${id}/report`, {
      method: 'POST',
      body: data,
      headers: key ? { 'Idempotency-Key': key } : {}
    }),
  overview: () => request('/api/v1/dashboard'),
  distribution: () => request('/api/v1/dashboard/status-distribution'),
  recentReports: (limit = 8) => request('/api/v1/dashboard/recent-reports', { params: { limit } }),
  realtime: () => request('/api/v1/dashboard/realtime'),
  equipmentSummary: (h = 24) =>
    request('/api/v1/dashboard/equipment-summary', { params: { since_hours: h } }),
  collectOnce: () => request('/api/v1/dashboard/gateway/collect', { method: 'POST' }),
  spcChart: (pid, code, tail = 30) =>
    request(`/api/v1/quality/spc/chart/${pid}/${code}`, { params: { tail } }),
  spcRules: () => request('/api/v1/quality/spc/rules'),
  addSubgroup: (data) => request('/api/v1/quality/spc/subgroups', { method: 'POST', body: data }),
  tasks: (params) => request('/api/v1/quality/tasks', { params }),
  taskMove: (id, data) => request(`/api/v1/quality/tasks/${id}/transition`, { method: 'POST', body: data }),
  stock: (params) => request('/api/v1/inventory', { params }),
  flows: (params) => request('/api/v1/inventory/transactions', { params }),
  issue: (data) => request('/api/v1/inventory/issue', { method: 'POST', body: data }),
  reportCatalog: () => request('/api/v1/reports'),
  reportQuery: (code, params) => request(`/api/v1/reports/${code}`, { params })
}

export const fmt = {
  pct: (v, d = 2) => (v === null || v === undefined ? '-' : `${Number(v).toFixed(d)}%`),
  num: (v, d = 0) => (v === null || v === undefined ? '-' : Number(v).toFixed(d)),
  date: (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '-')
}

export const ORDER_STATUS = {
  DRAFT: { label: '草稿', tone: 'muted' },
  RELEASED: { label: '已下达', tone: 'info' },
  IN_PROGRESS: { label: '生产中', tone: 'primary' },
  PAUSED: { label: '暂停', tone: 'warn' },
  COMPLETED: { label: '已完工', tone: 'success' },
  CANCELLED: { label: '已作废', tone: 'danger' }
}

export const OP_STATUS = {
  NOT_STARTED: { label: '未开工', tone: 'muted' },
  RUNNING: { label: '加工中', tone: 'primary' },
  FINISHED: { label: '已完成', tone: 'success' }
}

export const EQUIP_STATUS = {
  RUN: { label: '运行', tone: 'success' },
  IDLE: { label: '待机', tone: 'muted' },
  FAULT: { label: '故障', tone: 'danger' },
  MAINTAIN: { label: '维保', tone: 'warn' },
  OFFLINE: { label: '离线', tone: 'muted' }
}

export const QC_STATUS = {
  PENDING: { label: '待处理', tone: 'warn' },
  TESTING: { label: '检验中', tone: 'primary' },
  PASSED: { label: '合格', tone: 'success' },
  FAILED: { label: '不合格', tone: 'danger' },
  CLOSED: { label: '已关闭', tone: 'muted' }
}
