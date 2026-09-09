<template>
  <div class="home-view">
    <!-- 英雄区域 -->
    <div class="hero-section animate-fade-in-up">
      <div class="hero-badge">
        <SvgIcon name="spark" :size="16" />
        <span>AI 驱动的多 Agent 博客生成系统</span>
      </div>
      <h1 class="hero-title">
        让 AI 帮你写出
        <span class="gradient-text">精彩博客</span>
      </h1>
      <p class="hero-desc">
        输入主题，多 Agent 协作完成调研、标题、大纲、正文、审稿、配图、排版全流程
      </p>

      <!-- 问答输入框 -->
      <div class="input-card">
        <div class="input-wrapper">
          <SvgIcon name="edit" :size="22" class="input-icon" />
          <el-input
            v-model="topic"
            type="textarea"
            :rows="2"
            placeholder="输入你想写的博客主题，例如：Python 快速入门指南..."
            resize="none"
            @keydown.enter.ctrl="handleCreate"
          />
          <button class="send-btn" :disabled="!topic.trim() || creating" @click="handleCreate">
            <SvgIcon v-if="!creating" name="send" :size="20" />
            <SvgIcon v-else name="loading" :size="20" class="animate-spin" />
          </button>
        </div>
        <div class="input-hint">
          <span>按 Ctrl + Enter 快速生成</span>
        </div>
      </div>

      <!-- 示例主题 -->
      <div class="examples">
        <span class="examples-label">试试这些主题：</span>
        <div class="example-tags">
          <span
            v-for="example in examples"
            :key="example"
            class="example-tag"
            @click="topic = example"
          >
            {{ example }}
          </span>
        </div>
      </div>
    </div>

    <!-- 我的文章 -->
    <div class="articles-section" v-if="taskList.length > 0">
      <div class="section-header">
        <h2>我的文章</h2>
        <span class="article-count">{{ taskList.length }} 篇</span>
      </div>
      <div class="article-grid">
        <div
          v-for="task in taskList"
          :key="task.id"
          class="article-card"
          @click="goToTask(task)"
        >
          <div class="card-status" :class="getStatusClass(task.status)">
            <span class="status-dot"></span>
            {{ getStatusText(task.status) }}
          </div>
          <h3 class="card-topic">{{ task.topic }}</h3>
          <p v-if="task.selected_title" class="card-title">{{ task.selected_title }}</p>
          <div class="card-footer">
            <div class="card-meta">
              <SvgIcon name="clock" :size="14" />
              <span>{{ formatTime(task.created_at) }}</span>
            </div>
            <div class="card-badges">
              <span v-if="task.need_image" class="badge">
                <SvgIcon name="image" :size="12" />
                配图
              </span>
              <span class="badge-id">#{{ task.id }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="empty-state">
      <div class="empty-icon">
        <SvgIcon name="document" :size="48" />
      </div>
      <p>还没有文章，输入主题开始创作吧</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import { useTaskStore } from '@/stores/task'
import { createTask, generateTitles } from '@/api/task'

const router = useRouter()
const taskStore = useTaskStore()
const { taskList, loading, fetchTaskList } = taskStore

const topic = ref('')
const creating = ref(false)

const examples = [
  'Python 快速入门指南',
  'Vue 3 组合式 API 最佳实践',
  'Docker 容器化部署实战',
  'FastAPI 高性能后端开发',
  'LangGraph 多 Agent 开发教程'
]

const statusMap = {
  'PENDING': { text: '待生成', class: 'status-pending' },
  'RESEARCHING_TITLE': { text: '标题调研中', class: 'status-processing' },
  'TITLE_GENERATED': { text: '待选标题', class: 'status-warning' },
  'RESEARCHING_OUTLINE': { text: '大纲调研中', class: 'status-processing' },
  'OUTLINE_GENERATED': { text: '待确认大纲', class: 'status-warning' },
  'GENERATING_CONTENT': { text: '生成正文中', class: 'status-processing' },
  'REVIEWING': { text: '审稿中', class: 'status-processing' },
  'GENERATING_IMAGES': { text: '配图中', class: 'status-processing' },
  'FORMATTING': { text: '格式化中', class: 'status-processing' },
  'COMPLETED': { text: '已完成', class: 'status-success' },
  'FAILED': { text: '失败', class: 'status-failed' }
}

function getStatusText(status) {
  return statusMap[status]?.text || status
}

function getStatusClass(status) {
  return statusMap[status]?.class || 'status-pending'
}

function formatTime(timeStr) {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) + ' ' +
    date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

async function handleCreate() {
  if (!topic.value.trim()) {
    ElMessage.warning('请输入博客主题')
    return
  }

  creating.value = true
  try {
    const task = await createTask({ topic: topic.value.trim() })
    ElMessage.success('任务创建成功，正在生成标题...')
    await generateTitles(task.id)
    router.push(`/task/${task.id}/titles`)
  } catch (error) {
    console.error('创建任务失败:', error)
  } finally {
    creating.value = false
  }
}

function goToTask(task) {
  const status = task.status
  if (['COMPLETED'].includes(status)) {
    router.push(`/blog/${task.id}`)
  } else if (['OUTLINE_GENERATED'].includes(status)) {
    router.push(`/task/${task.id}/outline`)
  } else if (['GENERATING_CONTENT', 'REVIEWING', 'GENERATING_IMAGES', 'FORMATTING'].includes(status)) {
    router.push(`/task/${task.id}/generating`)
  } else {
    router.push(`/task/${task.id}/titles`)
  }
}

onMounted(() => {
  fetchTaskList()
})
</script>

<style scoped>
.home-view {
  max-width: 900px;
  margin: 0 auto;
}

/* 英雄区域 */
.hero-section {
  text-align: center;
  padding: 40px 0 60px;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  background: linear-gradient(135deg, #eef2ff 0%, #f5f3ff 100%);
  border: 1px solid #c7d2fe;
  border-radius: 20px;
  font-size: 13px;
  color: var(--primary-dark);
  font-weight: 500;
  margin-bottom: 24px;
}

.hero-title {
  font-size: 42px;
  font-weight: 800;
  line-height: 1.3;
  margin-bottom: 16px;
  color: var(--text-primary);
}

.gradient-text {
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-desc {
  font-size: 16px;
  color: var(--text-secondary);
  margin-bottom: 40px;
  max-width: 560px;
  margin-left: auto;
  margin-right: auto;
}

/* 输入框 */
.input-card {
  max-width: 640px;
  margin: 0 auto;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 16px;
  background: white;
  border-radius: 20px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  border: 2px solid var(--border);
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: var(--primary);
  box-shadow: 0 4px 24px rgba(99, 102, 241, 0.15);
}

.input-icon {
  color: var(--primary);
  margin-bottom: 8px;
  flex-shrink: 0;
}

.input-wrapper :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none !important;
  font-size: 15px;
  padding: 8px 0;
  resize: none;
}

.send-btn {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--primary-gradient);
  border: none;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-muted);
}

/* 示例标签 */
.examples {
  margin-top: 32px;
}

.examples-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-right: 8px;
}

.example-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 12px;
}

.example-tag {
  padding: 6px 14px;
  background: white;
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.example-tag:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: #f5f3ff;
}

/* 文章列表 */
.articles-section {
  margin-top: 60px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.section-header h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
}

.article-count {
  font-size: 14px;
  color: var(--text-muted);
}

.article-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.article-card {
  background: white;
  border-radius: 16px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.3s ease;
  border: 1px solid var(--border);
}

.article-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1);
  border-color: var(--primary-light);
}

.card-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 12px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-pending { background: #f1f5f9; color: #64748b; }
.status-processing { background: #dbeafe; color: #2563eb; }
.status-warning { background: #fef3c7; color: #d97706; }
.status-success { background: #d1fae5; color: #059669; }
.status-failed { background: #fee2e2; color: #dc2626; }

.card-topic {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-title {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 16px;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.card-badges {
  display: flex;
  align-items: center;
  gap: 8px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--warning);
  background: #fffbeb;
  padding: 2px 8px;
  border-radius: 8px;
}

.badge-id {
  font-size: 12px;
  color: var(--text-muted);
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--text-muted);
}

.empty-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}
</style>
