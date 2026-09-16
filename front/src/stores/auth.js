import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'

const TOKEN_KEY = 'blog-agent-token'
const USER_KEY = 'blog-agent-user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))

  const isLoggedIn = computed(() => !!token.value)

  function setAuth(t, u) {
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
    const res = await request.get('/auth/me')
    user.value = res
    localStorage.setItem(USER_KEY, JSON.stringify(res))
    return res
  }

  async function recharge(amount) {
    const res = await request.post('/auth/recharge', { amount })
    if (user.value) user.value.balance = res.balance
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    return res
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, user, isLoggedIn, login, register, fetchMe, recharge, logout }
})
