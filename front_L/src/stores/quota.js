import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import request from '@/utils/request'

export const useQuotaStore = defineStore('generation-quota', () => {
  const auth = useAuthStore()
  const quota = ref(null)
  const loading = ref(false)
  const unavailable = ref(false)
  const rejection = ref(null)
  const signedIn = computed(() => auth.isLoggedIn)
  let version = 0

  function rejectionKey() {
    return auth.user?.id != null && auth.token ? `blog-agent-admission:${auth.user.id}` : null
  }
  watch([() => auth.token, () => auth.user?.id], () => {
    version++
    quota.value = null
    loading.value = false
    unavailable.value = false
    let previous = null
    try { if (rejectionKey()) previous = JSON.parse(sessionStorage.getItem(rejectionKey())) } catch { /* Tab storage is optional. */ }
    rejection.value = previous
  }, { flush: 'sync', immediate: true })
  watch(rejection, value => {
    const key = rejectionKey()
    if (!key) return
    try {
      if (value) sessionStorage.setItem(key, JSON.stringify(value))
      else sessionStorage.removeItem(key)
    } catch { /* Keep the in-memory notice. */ }
  }, { flush: 'sync' })

  async function refresh(force = false) {
    if (!signedIn.value || (loading.value && force !== true)) return
    const revision = ++version
    loading.value = true
    try {
      const data = await request.get('/auth/quota')
      if (revision !== version) return
      if (!Number.isInteger(data?.remaining) || !Number.isInteger(data?.daily_limit) || !data.stage_costs) throw new Error('Incomplete quota response')
      quota.value = data
      unavailable.value = false
    } catch {
      if (revision !== version) return
      quota.value = null
      unavailable.value = true
    } finally {
      if (revision === version) loading.value = false
    }
  }
  function insufficient(stage) {
    return quota.value?.remaining < quota.value?.stage_costs?.[stage]
  }
  function recordAdmissionError(taskId, error, source) {
    if (![429, 503].includes(error.response?.status)) return
    const detail = error.response.data?.detail
    const retryHeader = error.response.headers?.['retry-after']
    const seconds = Number(retryHeader)
    const retryAt = retryHeader && Number.isFinite(seconds) ? Date.now() + seconds * 1000 : Date.parse(retryHeader)
    rejection.value = {
      taskId, message: typeof detail === 'string' ? detail : detail?.message || error.message,
      retryAt: Number.isFinite(retryAt) ? retryAt : null,
      status: source?.status, updatedAt: source?.updatedAt
    }
    void refresh(true)
  }
  return { quota, loading, unavailable, signedIn, rejection, refresh, insufficient, recordAdmissionError }
})
