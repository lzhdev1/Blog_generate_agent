<template>
  <div class="generating-view">
    <div class="steps-bar">
      <div class="step done"><div class="step-num">✓</div><span>创建任务</span></div>
      <div class="step-line"></div>
      <div class="step done"><div class="step-num">✓</div><span>选择标题</span></div>
      <div class="step-line"></div>
      <div class="step done"><div class="step-num">✓</div><span>确认大纲</span></div>
      <div class="step-line"></div>
      <div class="step active"><div class="step-num">4</div><span>生成文章</span></div>
    </div>

    <div class="content-card animate-fade-in-up">
      <ProgressModal
        :visible="true"
        type="content"
        :task-status="task?.status || ''"
        :progress-text="task?.progress || ''"
      />

      <div v-if="error" class="error-section">
        <div class="error-icon">
          <SvgIcon name="review" :size="24" />
        </div>
        <p>{{ error }}</p>
        <button class="btn-primary" @click="retry">重新生成</button>
      </div>

      <div class="actions" v-if="!completed && !error">
        <button class="btn-secondary" @click="$router.push('/')">
          后台继续生成，返回列表
        </button>
      </div>

      <div class="actions" v-if="completed">
        <button class="btn-primary" @click="$router.push(`/blog/${taskId}`)">
          <SvgIcon name="document" :size="16" />
          查看成品文章
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SvgIcon from '@/components/SvgIcon.vue'
import { getTask, generateContent } from '@/api/task'
import ProgressModal from '@/components/ProgressModal.vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const task = ref(null)
const error = ref('')
const completed = ref(false)
let pollTimer = null
let isGenerating = false
// SSE 推送通道（主通道，替代高频轮询；轮询仅作断线兜底）
let sseController = null       // AbortController：组件卸载/完成时主动断开
let sseRetryCount = 0
const MAX_SSE_RETRY = 3        // 连续重连失败 3 次后降级为 2s 轮询

const agents = [
  { key: 'research', name: '调研资料', icon: 'search', desc: '联网搜索最新资料' },
  { key: 'write', name: '撰写正文', icon: 'pen', desc: '撰写正文' },
  { key: 'review', name: '审阅文章', icon: 'review', desc: '审阅文章' },
  { key: 'image', name: '配图', icon: 'image', desc: '搜索/生成配图' },
  { key: 'format', name: '排版', icon: 'format', desc: '格式化文章' }
]

const statusMap = {
  'researching_content': { text: '调研资料中', percent: 15 },
  'generating_content': { text: '生成正文中', percent: 35 },
  'reviewing': { text: '审稿中', percent: 55 },
  'generating_images': { text: '配图中', percent: 75 },
  'formatting': { text: '格式化中', percent: 90 },
  'completed': { text: '已完成', percent: 100 }
}

const statusText = computed(() => statusMap[task.value?.status]?.text || '处理中')
// 进度只进不退：正文审稿打回时 status 会回退到 researching_content，
// 但"进度"是历史见过的最高阶段百分比，不跟着倒退（完成时强制 100）
const maxPercent = ref(0)
const progressPercent = computed(() => {
  if (task.value?.status === 'completed') return 100
  const cur = statusMap[task.value?.status]?.percent || 10
  if (maxPercent.value < cur) maxPercent.value = cur
  return maxPercent.value
})

function getAgentState(key) {
  const status = task.value?.status
  const order = ['research', 'write', 'review', 'image', 'format']
  const currentIdx = {
    'researching_content': 0,
    'generating_content': 1,
    'reviewing': 2,
    'generating_images': 3,
    'formatting': 4,
    'completed': 5
  }[status] ?? -1

  const idx = order.indexOf(key)
  if (status === 'completed') return 'done'
  if (idx < currentIdx) return 'done'
  if (idx === currentIdx) return 'active'
  return 'pending'
}

function getAgentStatusText(key) {
  const state = getAgentState(key)
  if (state === 'done') return '已完成'
  if (state === 'active') return task.value?.progress || '进行中...'
  return '等待中'
}

async function fetchTask() {
  try {
    task.value = await getTask(taskId)
    // 页面刷新/重新进入时，进度从当前阶段起步，不从 0 重新涨
    if (maxPercent.value === 0) {
      maxPercent.value = statusMap[task.value?.status]?.percent || 10
    }
    const status = task.value.status
    if (status === 'completed' || status === 'content_generated') {
      completed.value = true
      stopPolling()
      // 延迟跳转，让用户看到完成状态
      setTimeout(() => {
        router.push(`/blog/${taskId}`)
      }, 800)
    } else if (status === 'failed') {
      error.value = task.value.error || '任务执行失败，请重试'
      stopPolling()
    }
  } catch (e) {
    console.error('获取任务状态失败:', e)
  }
}

function startPolling() {
  pollTimer = setInterval(fetchTask, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ========== SSE 推送通道（主通道，替代 2s 轮询） ==========
// 服务端只在状态/进度变化时推送，客户端零轮询请求；断线自动重连，重连失败降级轮询。

function applyTaskUpdate(payload) {
  if (!task.value) task.value = {}
  if (payload.status) task.value.status = payload.status
  if (payload.progress) task.value.progress = payload.progress
  if (payload.error) task.value.error = payload.error
  const status = task.value.status
  if (status === 'completed' || status === 'content_generated') {
    completed.value = true
    stopStream()
    setTimeout(() => {
      router.push(`/blog/${taskId}`)
    }, 800)
  } else if (status === 'failed') {
    error.value = task.value.error || '任务执行失败，请重试'
    stopStream()
  }
}

async function startStream() {
  stopStream() // 防重入：先断开旧连接
  sseController = new AbortController()
  const token = localStorage.getItem('blog-agent-token')
  try {
    const res = await fetch(`/api/v1/task/${taskId}/stream`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: sseController.signal
    })
    if (!res.ok) throw new Error(`SSE HTTP ${res.status}`)
    sseRetryCount = 0
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() // 最后一段可能不完整，留到下一帧
      for (const raw of events) {
        const dataLine = raw.split('\n').find(l => l.startsWith('data:'))
        if (!dataLine) continue
        let data = {}
        try {
          data = JSON.parse(dataLine.slice(5).trim())
        } catch {
          continue // 跳过无法解析的帧
        }
        if (data.detail) {
          error.value = data.detail
          stopStream()
          return
        }
        applyTaskUpdate(data)
        if (completed.value || error.value) return
      }
    }
    // 流正常结束（后端推送终态后断开，或服务端关闭）
    if (!completed.value && !error.value) scheduleReconnect()
  } catch (e) {
    if (e.name === 'AbortError') return // 主动断开（组件卸载/跳转），不算失败
    console.error('SSE 连接失败:', e.message)
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (completed.value || error.value) return
  if (sseRetryCount >= MAX_SSE_RETRY) {
    console.warn('SSE 重连多次失败，降级为 2s 轮询兜底')
    startPolling()
    return
  }
  sseRetryCount++
  setTimeout(startStream, 3000) // 3s 后重连
}

function stopStream() {
  if (sseController) {
    sseController.abort()
    sseController = null
  }
}

async function startGeneration() {
  if (isGenerating) return
  isGenerating = true
  try {
    await generateContent(taskId)
    await fetchTask()
  } catch (e) {
    const detail = e.response?.data?.detail
    if (detail) {
      // 后端明确返回的业务错误（4xx/5xx）
      error.value = detail
      stopPolling()
    } else {
      // 网络层异常（超时/断连）：后端可能仍在执行，不立即判失败，
      // 交给轮询确认最终状态（completed 正常完成 / failed 才显示错误）
      console.error('生成请求异常（后端可能仍在执行，等待轮询确认）:', e.message)
    }
  } finally {
    isGenerating = false
  }
}

async function retry() {
  error.value = ''
  await startGeneration()
}

onMounted(async () => {
  await fetchTask()
  // SSE 为主通道推送进度；轮询仅作断线兜底（已完成/已失败的任务不再连）
  if (!completed.value && !error.value) startStream()
  // 如果大纲已确认，触发生成正文（异步执行，不阻塞 SSE）
  const status = task.value?.status
  if (status === 'outline_generated' && task.value?.outline_confirmed) {
    startGeneration()
  }
})

onUnmounted(() => {
  stopPolling()
  stopStream()
})
</script>

<style scoped>
.generating-view {
  max-width: 600px;
  margin: 0 auto;
}

.steps-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 32px;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.step-num {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--border);
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
}

.step.active .step-num {
  background: var(--primary-gradient);
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.step.done .step-num {
  background: var(--success);
  color: white;
}

.step span {
  font-size: 12px;
  color: var(--text-muted);
}

.step.active span {
  color: var(--primary);
  font-weight: 500;
}

.step-line {
  width: 50px;
  height: 2px;
  background: var(--border);
  margin: 0 8px;
  margin-bottom: 22px;
}

.content-card {
  background: var(--bg-card);
  border-radius: 20px;
  padding: 40px 32px;
  box-shadow: var(--shadow-md);
  text-align: center;
}

.generating-header {
  margin-bottom: 32px;
}

.generating-icon {
  width: 72px;
  height: 72px;
  margin: 0 auto 20px;
  border-radius: 20px;
  background: var(--primary-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.3);
}

.generating-header h2 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
}

.generating-desc {
  margin: 0;
  font-size: 15px;
  color: var(--primary);
  font-weight: 500;
}

.progress-section {
  margin-bottom: 32px;
}

.progress-bar-wrapper {
  height: 8px;
  background: var(--bg-soft);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 10px;
}

.progress-bar {
  height: 100%;
  background: var(--primary-gradient);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-secondary);
}

.agent-timeline {
  text-align: left;
  background: var(--bg-soft);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 28px;
}

.agent-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 0;
  opacity: 0.4;
  transition: all 0.3s ease;
}

.agent-item + .agent-item {
  border-top: 1px solid var(--border);
}

.agent-item.active {
  opacity: 1;
}

.agent-item.done {
  opacity: 0.7;
}

.agent-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--border);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-item.active .agent-icon {
  background: var(--primary-gradient);
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.agent-item.done .agent-icon {
  background: #d1fae5;
  color: #059669;
}

.agent-info {
  flex: 1;
}

.agent-name {
  font-size: 14px;
  font-weight: 600;
}

.agent-status {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.agent-item.active .agent-status {
  color: var(--primary);
}

.agent-state-icon {
  color: var(--success);
}

.error-section {
  padding: 24px;
  background: #fef2f2;
  border-radius: 14px;
  margin-bottom: 20px;
}

.error-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 12px;
  border-radius: 50%;
  background: #fee2e2;
  color: #dc2626;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error-section p {
  color: #dc2626;
  margin: 0 0 16px;
}

.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}

.btn-secondary {
  padding: 12px 24px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: 12px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 28px;
  border: none;
  background: var(--primary-gradient);
  color: white;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
}
</style>
