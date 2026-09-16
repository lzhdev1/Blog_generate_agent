<template>
  <div class="home-view">
    <!-- 英雄区域 -->
    <div class="hero-section animate-fade-in-up">
      <div class="hero-badge">
        <SvgIcon name="spark" :size="16" />
        <span>{{ $t('home.badge') }}</span>
      </div>
      <h1 class="hero-title">
        {{ $t('home.titlePart1') }}
        <span class="gradient-text">{{ $t('home.titlePart2') }}</span>
      </h1>

      <!-- 问答输入框 -->
      <div class="input-card">
        <!-- 背景词云（推荐主题，入场从底部散出 + 持续漂浮） -->
        <div class="word-cloud">
          <span
            v-for="(w, i) in cloudWords"
            :key="i"
            class="cloud-word"
            :class="{ entered: cloudEntered }"
            :style="{
              left: cloudEntered ? w.left : '50%',
              top: cloudEntered ? w.top : '50%',
              fontSize: w.size + 'px',
              '--op': w.opacity,
              '--dur': w.dur + 's',
              '--burst-delay': '0s',
              '--float-delay': '0.48s'
            }"
          >{{ w.text }}</span>
        </div>
        <div class="input-wrapper">
          <el-input
            v-model="topic"
            type="textarea"
            :rows="2"
            :placeholder="$t('home.placeholder')"
            resize="none"
            :disabled="creating"
            @keydown.enter.ctrl="handleCreate"
          />
          <button class="send-btn" :disabled="!topic.trim() || creating" @click="handleCreate">
            <SvgIcon v-if="!creating" name="send" :size="20" />
            <SvgIcon v-else name="loading" :size="20" class="animate-spin" />
          </button>
        </div>
      </div>
    </div>

    <!-- 全部文章 -->
    <div id="articles-section" class="articles-section">
      <div class="section-header">
        <h2>{{ $t('home.allArticles') }}</h2>
        <div class="section-actions">
          <button class="shuffle-btn" :disabled="shuffling" @click="fetchArticles">
            <SvgIcon name="refresh" :size="15" />
            <span>{{ $t('home.shuffle') }}</span>
          </button>
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
              {{ a.is_demo ? $t('home.demo') : $t('home.user') }}
            </span>
            <span class="card-price" :class="a.download_price > 0 ? 'is-paid' : 'is-free'">
              <SvgIcon name="download" :size="12" />
              {{ a.download_price > 0 ? `¥${a.download_price}` : $t('home.free') }}
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
              <span
                class="stat"
                :class="{ active: a.liked }"
                title="点赞"
                @click.stop="handleLike(a)"
              >
                <SvgIcon name="like" :size="13" /> {{ a.like_count }}
              </span>
              <span
                class="stat"
                :class="{ 'active-fav': a.favorited }"
                title="收藏"
                @click.stop="handleFavorite(a)"
              >
                <SvgIcon name="star" :size="13" /> {{ a.favorite_count }}
              </span>
              <span
                v-if="a.allow_download || a.is_demo"
                class="stat"
                title="下载"
                @click.stop="handleDownload(a)"
              >
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
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import ProgressModal from '@/components/ProgressModal.vue'
import { createTask, generateTitles, getTask } from '@/api/task'
import { getArticles, toggleLike, toggleFavorite, downloadArticle } from '@/api/article'
import { isTimeoutError } from '@/utils/request'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

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

// ===== 卡片交互：点赞 / 收藏 / 下载 =====
function handleLike(a) {
  toggleLike(a.task_id).then(res => {
    a.like_count = res.like_count
    a.liked = res.liked
  })
}

function handleFavorite(a) {
  toggleFavorite(a.task_id).then(res => {
    a.favorited = res.favorited
    a.favorite_count = Math.max(0, (a.favorite_count || 0) + (res.favorited ? 1 : -1))
  })
}

function handleDownload(a) {
  downloadArticle(a.task_id)
    .then(res => {
      const blob = new Blob([res.content || ''], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${res.title || 'article'}.md`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      ElMessage.success('下载成功')
    })
    .catch(() => {
      // 未购买/未登录等提示已由请求拦截器统一弹出
    })
}

const topic = ref('')
const creating = ref(false)
const progressText = ref('')
const showProgressModal = ref(false)
const currentTaskStatus = ref('')
let pollTimer = null

// ===== 环绕 + 背景词云（多领域推荐主题，漂浮动画） =====
// 背景组：贴近输入框上/下边框浮动，词被输入框半遮半露，营造立体感
// 环绕组：位于输入框四周，横向铺开、纵向收窄
const cloudWords = [
  // —— 背景组 · 贴上边框（骑跨输入框上沿） ——
  { text: 'Python', left: '6%', top: '30%', size: 22, dur: 7, delay: 0, opacity: 0.46, bg: true },
  { text: '机器学习', left: '38%', top: '32%', size: 17, dur: 6.8, delay: 2.6, opacity: 0.42, bg: true },
  { text: '机器人', left: '70%', top: '29%', size: 17, dur: 8.2, delay: 1.4, opacity: 0.42, bg: true },
  { text: '读书', left: '93%', top: '31%', size: 15, dur: 7.4, delay: 0.8, opacity: 0.38, bg: true },
  // —— 背景组 · 贴下边框（骑跨输入框下沿） ——
  { text: 'Docker', left: '12%', top: '76%', size: 19, dur: 8, delay: 0.6, opacity: 0.44, bg: true },
  { text: '大模型', left: '42%', top: '78%', size: 16, dur: 8.5, delay: 1.8, opacity: 0.4, bg: true },
  { text: '美食', left: '72%', top: '75%', size: 17, dur: 6.5, delay: 3.0, opacity: 0.42, bg: true },
  { text: '猫', left: '92%', top: '79%', size: 15, dur: 7.7, delay: 2.2, opacity: 0.38, bg: true },
  // —— 环绕组 · 上方 ——
  { text: 'Vue 3', left: '24%', top: '4%', size: 20, dur: 8, delay: 0.4, opacity: 0.55 },
  { text: 'LangGraph', left: '52%', top: '0%', size: 19, dur: 6.5, delay: 1.2, opacity: 0.5 },
  { text: 'AI Agent', left: '80%', top: '8%', size: 17, dur: 7.5, delay: 2.1, opacity: 0.46 },
  { text: '诗歌', left: '68%', top: '14%', size: 16, dur: 9, delay: 3.2, opacity: 0.42 },
  // —— 环绕组 · 下方 ——
  { text: 'FastAPI', left: '30%', top: '94%', size: 21, dur: 7.8, delay: 0.5, opacity: 0.55 },
  { text: '云原生', left: '58%', top: '98%', size: 17, dur: 6, delay: 0.3, opacity: 0.48 },
  { text: '旅行', left: '82%', top: '92%', size: 17, dur: 8.8, delay: 1.5, opacity: 0.46 },
  { text: '音乐', left: '8%', top: '96%', size: 16, dur: 7.2, delay: 2.8, opacity: 0.44 },
  // —— 环绕组 · 两侧（横向铺开） ——
  { text: '自动化', left: '-4%', top: '36%', size: 16, dur: 6.2, delay: 2.4, opacity: 0.44 },
  { text: '咖啡', left: '-3%', top: '60%', size: 14, dur: 8.4, delay: 0.7, opacity: 0.38 },
  { text: 'DevOps', left: '99%', top: '30%', size: 16, dur: 8.8, delay: 1.5, opacity: 0.44 },
  { text: '摄影', left: '100%', top: '55%', size: 15, dur: 7.6, delay: 3.4, opacity: 0.4 },
  { text: '小说', left: '101%', top: '74%', size: 15, dur: 6.9, delay: 1.1, opacity: 0.4 },
  { text: '天文', left: '44%', top: '-4%', size: 15, dur: 8.6, delay: 2.6, opacity: 0.42 }
]

// 词云入场控制（进入页面后从底部散出）
const cloudEntered = ref(false)

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
  // 未登录不允许发起生成任务：提示并跳转登录页（登录后跳回首页）
  if (!authStore.isLoggedIn) {
    ElMessage.warning('请先登录后再创建文章')
    router.push({ path: '/login', query: { redirect: '/' } })
    return
  }

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
  // 词云入场：先渲染"集中在中心"的初始状态，再触发爆炸扩散。
  // rAF + setTimeout 双保险：页面导航节流时 rAF 可能不触发，setTimeout 兜底
  let fired = false
  const fire = () => {
    if (fired) return
    fired = true
    cloudEntered.value = true
  }
  requestAnimationFrame(fire)
  setTimeout(fire, 120)
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
  position: relative;
  max-width: 640px;
  margin: 0 auto;
  padding: 42px 0;
}

/* 环绕词云层（输入框上下左右漂浮） */
.word-cloud {
  position: absolute;
  inset: -20px -50px;
  z-index: 0;
  overflow: visible;
  pointer-events: none;
  transform: translateY(24px);
}

.cloud-word {
  position: absolute;
  font-weight: 700;
  color: var(--primary);
  white-space: nowrap;
  user-select: none;
  /* 初始：集中在输入框中心，缩小不可见 */
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%) scale(0.1);
  opacity: 0;
  transition:
    left 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) var(--burst-delay, 0s),
    top 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) var(--burst-delay, 0s),
    transform 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) var(--burst-delay, 0s),
    opacity 0.32s ease var(--burst-delay, 0s);
}

.cloud-word.entered {
  /* 入场：从中心爆炸扩散到各自位置 */
  opacity: var(--op, 0.5);
  transform: translate(-50%, -50%) scale(1);
  /* 入场完成后持续漂浮 */
  animation: cloudFloat var(--dur, 8s) ease-in-out var(--float-delay, 1s) infinite;
}

[data-theme='dark'] .cloud-word {
  color: #818cf8;
}

@keyframes cloudFloat {
  0%, 100% { transform: translate(-50%, -50%) translateY(0) translateX(0); }
  33% { transform: translate(-50%, -50%) translateY(-9px) translateX(5px); }
  66% { transform: translate(-50%, -50%) translateY(7px) translateX(-5px); }
}

.input-wrapper {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.88);
  border-radius: 20px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  border: 2px solid var(--border);
  transition: all 0.3s ease;
}

[data-theme='dark'] .input-wrapper {
  background: rgba(24, 26, 40, 0.82);
}

/* 输入框本体透明，露出背景词云 */
.input-wrapper :deep(.el-textarea__inner) {
  background: transparent;
  box-shadow: none;
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

/* 换一批：文字按钮（无边框无背景） */
.shuffle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.shuffle-btn:hover {
  color: var(--primary);
  background: var(--bg-soft);
}

.shuffle-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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
  cursor: pointer;
  user-select: none;
  transition: color 0.2s ease;
}

.stat:hover {
  color: var(--primary);
}

/* 已点赞：玫红高亮 */
.stat.active {
  color: #f43f5e;
}

.stat.active svg {
  stroke: #f43f5e;
}

/* 已收藏：金色高亮 */
.stat.active-fav {
  color: #f59e0b;
}

.stat.active-fav svg {
  stroke: #f59e0b;
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
