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
          <el-input
            v-model="topic"
            type="textarea"
            :rows="2"
            placeholder="输入你想写的博客主题，例如：Python 快速入门指南..."
            resize="none"
            :disabled="creating"
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

    <!-- 全部文章 -->
    <div id="articles-section" class="articles-section">
      <div class="section-header">
        <h2>全部文章</h2>
        <div class="section-actions">
          <span class="article-count">{{ articleTotal }} 篇</span>
          <el-button size="small" :loading="shuffling" @click="fetchArticles">
            <SvgIcon name="refresh" :size="14" />
            换一批
          </el-button>
        </div>
      </div>

      <div v-if="articlesLoading && !articles.length" class="article-grid">
        <div v-for="i in 4" :key="i" class="article-card skeleton-card">
          <el-skeleton animated :rows="3" />
        </div>
      </div>

      <el-empty v-else-if="!articles.length" description="暂无公开文章" />

      <div v-else class="article-grid">
        <div
          v-for="a in articles"
          :key="a.task_id"
          class="article-card"
          @click="goArticle(a.task_id)"
        >
          <div class="card-top">
            <span class="card-type" :class="a.is_demo ? 'is-demo' : 'is-user'">
              {{ a.is_demo ? '演示' : '用户' }}
            </span>
            <span class="card-price" :class="a.download_price > 0 ? 'is-paid' : 'is-free'">
              <SvgIcon name="download" :size="12" />
              {{ a.download_price > 0 ? `¥${a.download_price}` : '免费' }}
            </span>
          </div>
          <h3 class="card-topic">{{ a.title }}</h3>
          <p v-if="a.topic" class="card-title">{{ a.topic }}</p>
          <div class="card-footer">
            <div class="card-author">
              <SvgIcon name="user" :size="13" />
              <span>{{ a.nickname || '匿名' }}</span>
            </div>
            <div class="card-stats">
              <span class="stat">
                <SvgIcon name="like" :size="13" /> {{ a.like_count }}
              </span>
              <span class="stat">
                <SvgIcon name="star" :size="13" /> {{ a.favorite_count }}
              </span>
              <span v-if="a.allow_download || a.is_demo" class="stat">
                <SvgIcon name="download" :size="13" />
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!articlesLoading && !articles.length" class="empty-state">
      <div class="empty-icon">
        <SvgIcon name="document" :size="48" />
      </div>
      <p>还没有文章，输入主题开始创作吧</p>
    </div>

    <!-- 进度弹窗 -->
    <ProgressModal
      :visible="showProgressModal"
      type="titles"
      :task-status="currentTaskStatus"
      :progress-text="progressText"
      @close="showProgressModal = false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import ProgressModal from '@/components/ProgressModal.vue'
import { createTask, generateTitles, getTask } from '@/api/task'
import { getArticles } from '@/api/article'
import { isTimeoutError } from '@/utils/request'

const router = useRouter()

// ===== 全部文章（随机展示 + 换一批） =====
const articles = ref([])
const articleTotal = ref(0)
const articlesLoading = ref(false)
const shuffling = ref(false)

async function fetchArticles() {
  shuffling.value = true
  if (!articles.value.length) articlesLoading.value = true
  try {
    const res = await getArticles({ limit: 8, offset: 0, random: true })
    articles.value = res.items || []
    articleTotal.value = res.total || 0
  } finally {
    articlesLoading.value = false
    shuffling.value = false
  }
}

function goArticle(taskId) {
  router.push(`/blog/${taskId}`)
}

const topic = ref('')
const creating = ref(false)
const progressText = ref('')
const showProgressModal = ref(false)
const currentTaskStatus = ref('')
let pollTimer = null

const examples = [
  'Python 快速入门指南',
  'Vue 3 组合式 API 最佳实践',
  'Docker 容器化部署实战',
  'FastAPI 高性能后端开发',
  'LangGraph 多 Agent 开发教程'
]

function formatTime(timeStr) {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) + ' ' +
    date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function startProgressPolling(taskId) {
  pollTimer = setInterval(async () => {
    try {
      const task = await getTask(taskId)
      currentTaskStatus.value = task.status
      if (task.progress) {
        progressText.value = task.progress
      }
      if (task.status === 'title_generated') {
        stopProgressPolling()
        showProgressModal.value = false
        creating.value = false
        router.push(`/task/${taskId}/titles`)
      }
      if (task.status === 'failed') {
        stopProgressPolling()
        showProgressModal.value = false
        creating.value = false
        ElMessage.error(task.error || '生成标题失败')
      }
    } catch (e) {
      console.error('轮询进度失败:', e)
    }
  }, 1500)
}

function stopProgressPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function handleCreate() {
  if (!topic.value.trim()) {
    ElMessage.warning('请输入博客主题')
    return
  }

  creating.value = true
  progressText.value = '正在创建任务...'
  currentTaskStatus.value = 'pending'
  showProgressModal.value = true
  try {
    const task = await createTask({ topic: topic.value.trim() })
    currentTaskStatus.value = task.status
    // 启动轮询展示进度
    startProgressPolling(task.id)
    // 异步触发生成标题（不阻塞）
    generateTitles(task.id).catch(err => {
      // 网关/连接超时：任务可能仍在后台生成标题，继续轮询等待，不误报失败
      if (isTimeoutError(err)) {
        console.warn('请求超时，任务可能仍在后台处理，继续轮询等待:', err)
        progressText.value = '处理时间较长，任务仍在后台运行中，请耐心等待...'
        return
      }
      console.error('生成标题失败:', err)
      stopProgressPolling()
      showProgressModal.value = false
      creating.value = false
      ElMessage.error('生成标题失败')
    })
  } catch (error) {
    console.error('创建任务失败:', error)
    creating.value = false
    showProgressModal.value = false
    progressText.value = ''
  }
}

onUnmounted(() => {
  stopProgressPolling()
})

onMounted(() => {
  fetchArticles()
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
  background: var(--panel-gradient);
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
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-card);
  border-radius: 20px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  border: 2px solid var(--border);
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: var(--primary);
  box-shadow: 0 4px 24px rgba(99, 102, 241, 0.15);
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

.progress-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--primary);
  font-weight: 500;
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
  background: var(--bg-card);
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
  background: var(--panel-gradient);
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
  position: relative;
  background: var(--bg-card);
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

/* 卡片顶部：左类型 / 右价格 */
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-price {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.card-price.is-free {
  background: #ecfdf5;
  color: #059669;
}

.card-price.is-paid {
  background: #fff7ed;
  color: #ea580c;
}

.card-price.is-paid svg {
  stroke: #ea580c;
}

.card-delete {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.2s ease;
  z-index: 2;
}

.article-card:hover .card-delete {
  opacity: 1;
}

.card-delete:hover {
  background: #fee2e2;
  color: #dc2626;
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

.status-pending { background: var(--bg-soft); color: var(--text-secondary); }
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

.card-author {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

/* 卡片右下角：点赞 / 收藏 / 下载 */
.card-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text-muted);
}

.stat {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--text-secondary);
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
  background: var(--bg-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}
</style>
