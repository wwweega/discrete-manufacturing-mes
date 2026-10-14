import { defineStore } from 'pinia'
import { reactive, computed } from 'vue'
import { authApi } from '../api/modules'
import { clearToken, getLocalUser, setLocalUser, setToken } from '../api/request'

/** 会话与权限：登录后把角色/权限码缓存下来，用于前端菜单与按钮的显隐控制。 */
export const useAuthStore = defineStore('auth', () => {
  const user = reactive(getLocalUser() || { username: '', roles: [], permissions: [] })

  const isLogin = computed(() => Boolean(user.username))
  const roleText = computed(() => {
    const map = { admin: '管理员', line_leader: '班组长', operator: '操作工' }
    return (user.roles || []).map((r) => map[r] || r).join(' / ') || '-'
  })

  const can = (code) => (user.permissions || []).includes(code)

  async function login(username, password) {
    const data = await authApi.login({ username, password })
    setToken(data.access_token)
    Object.assign(user, {
      username: data.username,
      real_name: data.real_name,
      roles: data.roles,
      permissions: data.permissions
    })
    setLocalUser(user)
    return user
  }

  function logout() {
    clearToken()
    Object.assign(user, { username: '', roles: [], permissions: [] })
  }

  return { user, isLogin, roleText, can, login, logout }
})
