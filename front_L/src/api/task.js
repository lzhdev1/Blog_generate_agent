import request from '@/utils/request'
import { useQuotaStore } from '@/stores/quota'
import { useAuthStore } from '@/stores/auth'
import { shallowReactive } from 'vue'
import { admissionWasRejected, createGenerationJournal, hasReceipt } from '@/utils/generationJournal'

const journal = createGenerationJournal(shallowReactive(new Map()), () => sessionStorage)
const account = () => useAuthStore().user?.id

export function pendingGeneration(taskId) {
  return journal.read(account(), taskId)
}

export function reconcileGeneration(task) {
  const pending = pendingGeneration(task.id)
  if (hasReceipt(pending, task)) journal.save(account(), task.id, null)
}

async function sendGeneration(taskId, record) {
  const quota = useQuotaStore()
  const auth = useAuthStore()
  const token = auth.token
  const owner = account()
  const forget = () => {
    if (journal.read(owner, taskId)?.id === record.id) journal.save(owner, taskId, null)
  }
  try {
    const result = await request.post(`/task/${taskId}/${record.endpoint}`, record.data, {
      headers: { 'Idempotency-Key': record.id }, timeout: 15000
    })
    forget()
    if (auth.token === token) {
      quota.rejection = null
      void quota.refresh(true)
    }
    return result
  } catch (error) {
    if (admissionWasRejected(error)) {
      forget()
      if (auth.token === token) quota.recordAdmissionError(taskId, error, record)
    }
    throw error
  }
}

async function enqueue(task, endpoint, data) {
  if (account() == null) await useAuthStore().fetchMe()
  const pending = pendingGeneration(task.id)
  if (pending) throw new Error('请先核对上次生成请求 / Resolve your last submission first.')
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
  const record = { id, endpoint, data, status: task.status, updatedAt: task.updated_at }
  journal.save(account(), task.id, record)
  useQuotaStore().rejection = null
  return sendGeneration(task.id, record)
}

export function replayGeneration(taskId) {
  const pending = pendingGeneration(taskId)
  if (pending) return sendGeneration(taskId, pending)
}

// 创建任务
export function createTask(data) {
  return request.post('/task', data)
}

// 生成标题
export function generateTitles(task) {
  return enqueue(task, 'generate-titles')
}

// 提交标题配置
export function submitTitleConfig(task, data) {
  return enqueue(task, 'submit-title-config', data)
}

// 重新生成大纲
export function regenerateOutline(task) {
  return enqueue(task, 'regenerate-outline')
}

// 确认大纲（可传入修改后的大纲 + 正文写作配置：字数/水平/额外要求）
export function confirmOutline(taskId, data = {}) {
  return request.post(`/task/${taskId}/confirm-outline`, data)
}

// Enqueue the confirmed outline. Progress is delivered separately by SSE.
export function generateContent(task) {
  return enqueue(task, 'generate-content')
}

// 获取任务详情
export function getTask(taskId) {
  const pending = pendingGeneration(taskId)
  return request.get(`/task/${taskId}`, {
    timeout: 15000, headers: pending ? { 'Idempotency-Key': pending.id } : {}
  })
}

// 获取任务列表
export function getTaskList(params) {
  return request.get('/task', { params })
}

// 删除任务
export function deleteTask(taskId) {
  return request.delete(`/task/${taskId}`)
}

// 获取博客详情
export function getBlogDetail(blogId) {
  return request.get(`/blog/${blogId}`)
}

export function reopenOutline(taskId) {
  return request.post(`/task/${taskId}/reopen-outline`)
}

export function restorePrevious(taskId) {
  return request.post(`/task/${taskId}/restore-previous`, undefined, { timeout: 15000 })
}

export const getRevision = (taskId, background = false) => request.get(`/task/${taskId}/revision`, {
  timeout: 15000, quietTransientError: background
})
export const saveRevision = (taskId, data) => request.put(`/task/${taskId}/revision`, data)
export const reviewRevision = (taskId, version, key) => request.post(`/task/${taskId}/revision/review`,
  { expected_version: version }, { headers: { 'Idempotency-Key': key }, timeout: 15000 })
export const applyRevision = (taskId, data) => request.post(`/task/${taskId}/revision/apply`, data)
export const discardRevision = (taskId, version) => request.delete(`/task/${taskId}/revision`, { params: { expected_version: version } })
