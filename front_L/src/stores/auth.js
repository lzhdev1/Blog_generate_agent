import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'

const TOKEN_KEY = 'blog-agent-token'
const USER_KEY = 'blog-agent-user'

function cachedUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY)) || null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(token.value ? cachedUser() : null)
  let revision = 0

  const isLoggedIn = computed(() => !!token.value)

  function setAuth(t, u) {
    revision++
    token.value = t
    user.value = u
    localStorage.setItem(TOKEN_KEY, t)
    localStorage.setItem(USER_KEY, JSON.stringify(u))
  }

  async function login(account, password) {
    const res = await request.post('/auth/login', { account, password })
    setAuth(res.access_token, res.user)
    return res.user
  }

  async function register(data) {
    const res = await request.post('/auth/register', data)
    setAuth(res.access_token, res.user)
    return res.user
  }

  async function fetchMe() {
    const started = revision
    const res = await request.get('/auth/me')
    if (started !== revision) return user.value
    user.value = res
    localStorage.setItem(USER_KEY, JSON.stringify(res))
    return res
  }

  async function recharge(amount, verifyCode) {
    const session = token.value
    const res = await request.post('/auth/recharge', { amount, verify_code: verifyCode })
    if (session === token.value && user.value) {
      revision++
      user.value = { ...user.value, balance: res.balance }
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    }
    return res
  }

  function logout() {
    revision++
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, user, isLoggedIn, login, register, fetchMe, recharge, logout }
})
