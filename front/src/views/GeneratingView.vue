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
      <div class="generating-header">
        <div class="generating-icon animate-pulse">
          <SvgIcon name="magic" :size="32" />
        </div>
        <h2>AI 正在创作中</h2>
        <p class="generating-desc">{{ task?.progress || '正在准备...' }}</p>
      </div>

      <div class="progress-section">
        <div class="progress-bar-wrapper">
          <div class="progress-bar" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <div class="progress-info">
          <span>{{ statusText }}</span>
          <span>{{ progressPercent }}%</span>
        </div>
      </div>

      <div class="agent-timeline">
        <div
          v-for="agent in agents"
          :key="agent.key"
          class="agent-item"
          :class="getAgentState(agent.key)"
        >
          <div class="agent-icon">
            <SvgIcon :name="agent.icon" :size="20" />
          </div>
          <div class="agent-info">
            <div class="agent-name">{{ agent.name }}</div>
            <div class="agent-status">{{ getAgentStatusText(agent.key) }}</div>
          </div>
          <div class="agent-state-icon">
            <SvgIcon v-if="getAgentState(agent.key) === 'done'" name="check" :size="18" />
            <SvgIcon v-else-if="getAgentState(agent.key) === 'active'" name="loading" :size="18" class="animate-spin" />
          </div>
        </div>
      </div>

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

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const task = ref(null)
const error = ref('')
const completed = ref(false)
let pollTimer = null

const agents = [
  { key: 'write', name: '写手 Agent', icon: 'pen', desc: '撰写正文' },
  { key: 'review', name: '审稿 Agent', icon: 'review', desc: '审阅文章' },
  { key: 'image', name: '配图 Agent', icon: 'image', desc: '搜索/生成配图' },
  { key: 'format', name: '排版 Agent', icon: 'format', desc: '格式化文章' }
]

const statusMap = {
  'GENERATING_CONTENT': { text: '生成正文中', percent: 25 },
  'REVIEWING': { text: '审稿中', percent: 50 },
  'GENERATING_IMAGES': { text: '配图中', percent: 75 },
  'FORMATTING': { text: '格式化中', percent: 90 },
  'COMPLETED': { text: '已完成', percent: 100 }
}

const statusText = computed(() => statusMap[task.value?.status]?.text || '处理中')
const progressPercent = computed(() => statusMap[task.value?.status]?.percent || 10)

function getAgentState(key) {
  const status = task.value?.status
  const order = ['write', 'review', 'image', 'format']
  const currentIdx = {
    'GENERATING_CONTENT': 0,
    'REVIEWING': 1,
    'GENERATING_IMAGES': 2,
    'FORMATTING': 3,
    'COMPLETED': 4
  }[status] ?? -1

  const idx = order.indexOf(key)
  if (status === 'COMPLETED') return 'done'
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
    if (task.value.status === 'COMPLETED') {
      completed.value = true
      stopPolling()
    } else if (task.value.status === 'FAILED') {
      error.value = '任务执行失败，请重试'
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

async function startGeneration() {
  try {
    await generateContent(taskId)
    await fetchTask()
  } catch (e) {
    error.value = e.response?.data?.detail || '生成失败，请重试'
  }
}

async function retry() {
  error.value = ''
  await startGeneration()
}

onMounted(async () => {
  await fetchTask()
  if (task.value?.status === 'OUTLINE_CONFIRMED' || task.value?.status === 'OUTLINE_GENERATED') {
    await startGeneration()
  }
  startPolling()
})

onUnmounted(() => {
  stopPolling()
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
  background: #e2e8f0;
  color: #94a3b8;
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
  background: #e2e8f0;
  margin: 0 8px;
  margin-bottom: 22px;
}

.content-card {
  background: white;
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
  background: #f1f5f9;
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
  background: #f8fafc;
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
  border-top: 1px solid #e2e8f0;
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
  background: #e2e8f0;
  color: #64748b;
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
  background: white;
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
