/**
 * 统一请求封装。
 *
 * 约定：后端所有接口返回 { code, msg, data }，code=0 视为成功；
 * 401 自动清理会话并跳转登录；其余非零码直接抛出可读错误交给页面提示。
 */

const TOKEN_KEY = 'mes_token'
const USER_KEY = 'mes_user'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
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
export const setLocalUser = (user) =>
  localStorage.setItem(USER_KEY, JSON.stringify(user))

class ApiError extends Error {
  constructor(code, msg, data) {
    super(msg)
    this.code = code
    this.data = data
  }
}

const buildUrl = (url) => (url.startsWith('/') ? url : `/${url}`)

async function request(url, options = {}) {
  const { method = 'GET', params, body, headers = {}, raw = false } = options

  let finalUrl = buildUrl(url)
  if (params) {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        search.append(key, value)
      }
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

  if (raw) return res

  let payload = null
  try {
    payload = await res.json()
  } catch {
    throw new ApiError(res.status, '响应解析失败', null)
  }

  if (payload.code === 401 || res.status === 401) {
    clearToken()
    if (window.location.hash !== '#/login') window.location.hash = '#/login'
    throw new ApiError(401, payload.msg || '登录已失效，请重新登录', payload.data)
  }
  if (!res.ok || payload.code !== 0) {
    throw new ApiError(payload.code ?? res.status, payload.msg || '请求失败', payload.data)
  }
  return payload.data
}

export const http = {
  get: (url, params, opts = {}) => request(url, { ...opts, method: 'GET', params }),
  post: (url, body, opts = {}) => request(url, { ...opts, method: 'POST', body }),
  put: (url, body, opts = {}) => request(url, { ...opts, method: 'PUT', body }),
  del: (url, opts = {}) => request(url, { ...opts, method: 'DELETE' })
}

export { ApiError }
