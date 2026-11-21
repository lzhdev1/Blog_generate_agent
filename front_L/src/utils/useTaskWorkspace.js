import { ref, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTask, pendingGeneration, reconcileGeneration, replayGeneration, restorePrevious } from '@/api/task'
import { useAuthStore } from '@/stores/auth'
import { useQuotaStore } from '@/stores/quota'
import { activeTaskStates, taskPath } from './taskWorkflow'

function errorMessage(error) {
  const detail = error.response?.data?.detail
  if (typeof detail?.message === 'string') return detail.message
  if (Array.isArray(detail)) return detail.map(item => item.msg).join(' · ')
  return detail || error.message
}

export function useTaskWorkspace() {
  const route = useRoute()
  const router = useRouter()
  const page = route.name
  const quota = useQuotaStore()
  const auth = useAuthStore()
  const task = ref(null)
  const error = ref('')
  const busy = ref(false)
  let epoch = 0
  let stream
  let timer

  function stop() {
    epoch++
    stream?.abort()
    clearTimeout(timer)
  }
  function current(version) {
    return version === epoch && route.name === page
  }
  function readFailed(version, cause) {
    if (!current(version)) return
    // The last editable snapshot may precede an accepted generation request.
    // Offer a read-only refresh before enabling another chargeable action.
    task.value = null
    error.value = errorMessage(cause)
  }
  async function read(version) {
    const data = await getTask(route.params.id)
    if (!current(version)) return false
    reconcileGeneration(data)
    const refused = quota.rejection
    if (refused?.status && String(refused.taskId) === String(data.id) && refused.status !== data.status) {
      quota.rejection = null
    }
    if (activeTaskStates.has(task.value?.status) && !activeTaskStates.has(data.status)) void quota.refresh(true)
    const path = ['completed', 'content_generated'].includes(data.status) && pendingGeneration(data.id)
      ? `/task/${data.id}/generating` : taskPath(data)
    if (path !== route.path) {
      await router.replace(path)
      return false
    }
    task.value = data
    return activeTaskStates.has(data.status)
  }

  // A disconnected stream falls back to serial GETs. Stop after a network error
  // and offer a reconnect, rather than stacking requests against a failing server.
  async function poll(version) {
    if (!current(version)) return
    try {
      if (await read(version)) timer = setTimeout(() => poll(version), 2500)
    } catch (cause) {
      readFailed(version, cause)
    }
  }
  async function subscribe(version) {
    const connection = new AbortController()
    stream = connection
    // Proxies occasionally leave a silent socket open. Recheck the authoritative
    // status after silence, including time spent waiting for response headers.
    let silent = false
    let watchdog
    function resetWatchdog() {
      clearTimeout(watchdog)
      watchdog = setTimeout(() => { silent = true; connection.abort() }, 45000)
    }
    resetWatchdog()
    try {
      const token = localStorage.getItem('blog-agent-token')
      const response = await fetch(`/api/v1/task/${route.params.id}/stream`, {
        headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` },
        signal: connection.signal
      })
      if (!response.ok || !response.headers.get('content-type')?.includes('text/event-stream')) {
        throw new Error('Stream unavailable')
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (current(version)) {
        const chunk = await reader.read()
        if (chunk.done || !current(version)) break
        resetWatchdog()
        buffer += decoder.decode(chunk.value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const update = JSON.parse(line.slice(5))
          if (!update.status) continue
          const next = { ...task.value, ...update }
          if (!activeTaskStates.has(update.status) || taskPath(next) !== route.path) {
            connection.abort()
            await poll(version) // GET the artifact and any saved configuration.
            return
          }
          task.value = next
        }
      }
    } catch (cause) {
      if (cause.name === 'AbortError' && !silent) return
    } finally {
      clearTimeout(watchdog)
    }
    if (current(version)) {
      if (silent) await reload()
      else await poll(version)
    }
  }

  async function reload() {
    stop()
    const version = epoch
    error.value = ''
    try {
      if (await read(version)) void subscribe(version)
    } catch (cause) {
      readFailed(version, cause)
    }
  }
  async function run(action) {
    if (busy.value || !task.value) return false
    const id = task.value.id
    stop()
    const version = epoch
    busy.value = true
    error.value = ''
    try {
      await action(id)
      if (current(version)) await reload()
      return true
    } catch (cause) {
      if (current(version)) {
        // The server may have accepted a request even if its response was lost.
        await reload()
        if (route.name === page && task.value?.id === id && !activeTaskStates.has(task.value.status)) {
          error.value ||= errorMessage(cause)
        }
      }
      return false
    } finally {
      if (String(id) === route.params.id) busy.value = false
    }
  }
  watch(() => route.params.id, () => {
    if (route.name === page) {
      busy.value = false
      task.value = null
      void reload()
    }
  }, { immediate: true })
  onBeforeUnmount(stop)
  function restore() {
    return run(async id => {
      const owner = task.value.user_id ?? auth.user?.id
      await restorePrevious(id)
      for (const stage of ['titles', 'outline']) {
        const key = `blog-agent-draft:${owner}:${stage}:${id}`
        try {
          sessionStorage.removeItem(key)
          sessionStorage.removeItem(key + ':settings')
        } catch { /* The restored server snapshot is authoritative. */ }
      }
    })
  }
  return { task, error, busy, run, reload, replay: () => run(replayGeneration), restore }
}

// Keep edits in this tab across refreshes. An independently regenerated artifact
// has a different source and must never inherit edits to its predecessor.
export function useTaskDraft(task, stage, source, defaults) {
  const auth = useAuthStore()
  const form = ref({})
  let key = ''
  let original
  let revision
  watch(() => [task.value?.id, task.value && source(task.value), task.value?.updated_at], ([id, value, at]) => {
    if (!id || !value) {
      key = ''
      return
    }
    const owner = task.value.user_id ?? auth.user?.id
    const nextKey = `blog-agent-draft:${owner}:${stage}:${id}`
    if (nextKey === key && value === original && at === revision) return
    key = nextKey
    original = value
    revision = at
    let saved
    let carried
    try {
      saved = JSON.parse(sessionStorage.getItem(key))
      const settings = JSON.parse(sessionStorage.getItem(key + ':settings'))
      if (settings && (settings.source !== value ||
        (settings.updatedAt && settings.updatedAt !== task.value.updated_at))) {
        carried = settings.fields
        sessionStorage.removeItem(key + ':settings')
      }
      // Old draft keys use globally unique task IDs. Only adopt one after the
      // server has returned the authenticated owner's task.
      if (!saved && owner != null && task.value.user_id === auth.user?.id) {
        const oldKey = `blog-agent-draft:${stage}:${id}`
        saved = JSON.parse(sessionStorage.getItem(oldKey))
        if (saved) sessionStorage.removeItem(oldKey)
      }
    } catch { /* Storage is optional. */ }
    form.value = {
      ...defaults(task.value),
      ...(carried || (saved?.source === original ? saved.form : {}))
    }
  }, { immediate: true, flush: 'sync' })
  watch(form, value => {
    if (!key) return
    try { sessionStorage.setItem(key, JSON.stringify({ source: original, form: value })) } catch { /* Quota or storage disabled. */ }
  }, { deep: true, flush: 'sync' })
  function clearDraft(id) {
    const owner = task.value?.user_id ?? auth.user?.id
    const draftKey = `blog-agent-draft:${owner}:${stage}:${id}`
    try {
      sessionStorage.removeItem(draftKey)
      sessionStorage.removeItem(draftKey + ':settings')
    } catch { /* Storage is optional. */ }
  }
  function keepSettings(fields) {
    if (!key) return
    const settings = Object.fromEntries(fields.map(name => [name, form.value[name]]))
    try {
      sessionStorage.setItem(key + ':settings', JSON.stringify({ source: original, updatedAt: task.value.updated_at, fields: settings }))
    } catch { /* Storage is optional. */ }
  }
  return { form, clearDraft, keepSettings }
}
