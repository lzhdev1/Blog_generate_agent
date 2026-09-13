<template>
  <div class="blog-detail-view">
    <!-- 顶部操作栏 -->
    <div class="blog-toolbar">
      <button class="toolbar-btn" @click="$router.push('/')">
        <SvgIcon name="back" :size="18" />
        <span>返回列表</span>
      </button>
      <div class="toolbar-actions">
        <button class="toolbar-btn" @click="copyContent">
          <SvgIcon name="copy" :size="16" />
          <span>复制全文</span>
        </button>
        <button class="toolbar-btn primary" @click="regenerate">
          <SvgIcon name="refresh" :size="16" />
          <span>重新生成</span>
        </button>
      </div>
    </div>

    <div v-if="blog" class="three-column">
      <!-- ========== 左栏：标题 / 大纲配置 / 大纲结构 ========== -->
      <aside class="side-col left-col">
        <div class="side-card">
          <div class="side-title">
            <SvgIcon name="spark" :size="14" />
            <span>用户选择的标题</span>
          </div>
          <p class="selected-title">{{ blog.selected_title || blog.topic || '—' }}</p>
        </div>

        <div class="side-card">
          <div class="side-title">
            <SvgIcon name="document" :size="14" />
            <span>大纲配置</span>
          </div>
          <table class="config-table">
            <tbody>
              <tr>
                <td>目标字数</td>
                <td>{{ blog.target_word_count ? `约 ${blog.target_word_count} 字` : '未指定' }}</td>
              </tr>
              <tr>
                <td>专业水平</td>
                <td>{{ levelLabel }}</td>
              </tr>
              <tr>
                <td>配图</td>
                <td>{{ blog.need_image ? `${imageSourceLabel}` : '不需要' }}</td>
              </tr>
              <tr v-if="blog.article_style">
                <td>文章风格</td>
                <td>{{ styleLabel }}</td>
              </tr>
              <tr>
                <td>对大纲的要求</td>
                <td>{{ blog.extra_requirements || '无' }}</td>
              </tr>
              <tr>
                <td>对正文的要求</td>
                <td>{{ blog.content_extra_requirements || '无' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="side-card">
          <div class="side-title collapsible" @click="toggle('outline')">
            <SvgIcon name="outline" :size="14" />
            <span>大纲结构</span>
            <SvgIcon :name="opened.outline ? 'up' : 'down'" :size="14" class="arrow" />
          </div>
          <div v-if="opened.outline" class="side-body">
            <MarkdownRender :content="blog.outline || '暂无大纲'" />
          </div>
        </div>
      </aside>

      <!-- ========== 中间栏：正文（宽度保持原样） ========== -->
      <main class="content-col">
        <div class="blog-card animate-fade-in-up">
          <article class="blog-article">
            <header class="blog-header">
              <div class="blog-badge">
                <SvgIcon name="spark" :size="14" />
                <span>AI 生成</span>
              </div>
              <h1 class="blog-title">{{ blog.selected_title || blog.topic }}</h1>
              <div class="blog-meta">
                <div class="meta-item">
                  <SvgIcon name="clock" :size="14" />
                  <span>{{ formatTime(blog.created_at) }}</span>
                </div>
                <div class="meta-item">
                  <SvgIcon name="document" :size="14" />
                  <span>约 {{ wordCount }} 字</span>
                </div>
                <div v-if="blog.image_urls?.length" class="meta-item">
                  <SvgIcon name="image" :size="14" />
                  <span>{{ blog.image_urls.length }} 张配图</span>
                </div>
              </div>
            </header>

            <div class="blog-divider"></div>

            <div class="blog-content">
              <MarkdownRender :content="blog.formatted_content || blog.content" />
            </div>
          </article>
        </div>
      </main>

      <!-- ========== 右栏：审稿记录 / 写手思路 / 调研结果 ========== -->
      <aside class="side-col right-col">
        <!-- 审稿记录（最上边，默认展开） -->
        <div class="side-card">
          <div class="side-title collapsible" @click="toggle('review')">
            <SvgIcon name="review" :size="14" />
            <span>审稿记录</span>
            <SvgIcon :name="opened.review ? 'up' : 'down'" :size="14" class="arrow" />
          </div>
          <div v-if="opened.review" class="side-body">
            <template v-if="reviewData">
              <!-- 综合评分 -->
              <div class="review-score-row">
                <div class="review-score">
                  <span class="score-num">{{ reviewData.score || 0 }}</span>
                  <span class="score-max">/100</span>
                </div>
                <div class="review-status" :class="reviewData.passed ? 'passed' : 'failed'">
                  {{ reviewData.passed ? '✓ 通过' : '✗ 未通过' }}
                </div>
              </div>

              <!-- 通过理由 -->
              <div v-if="reviewData.pass_reasons && reviewData.pass_reasons.length" class="review-pass-reasons">
                <div class="pass-reasons-title">通过理由</div>
                <ul class="pass-reasons-list">
                  <li v-for="(reason, i) in reviewData.pass_reasons" :key="i">{{ reason }}</li>
                </ul>
              </div>
              <!-- 兼容旧数据：没有pass_reasons但有feedback时显示总体评价 -->
              <div v-else-if="reviewData.feedback" class="review-feedback">
                <div class="feedback-title">总体评价</div>
                <MarkdownRender :content="reviewData.feedback" />
              </div>

              <!-- 流量预测 -->
              <div v-if="reviewData.traffic_forecast || reviewData.heat_level" class="review-traffic">
                <div class="traffic-title">流量预测</div>
                <div class="traffic-value">
                  <span class="heat-dot" :style="{ background: (HEAT_LEVEL_CONFIG[reviewData.traffic_forecast || reviewData.heat_level] || HEAT_LEVEL_CONFIG['一般']).color }"></span>
                  <span :style="{ color: (HEAT_LEVEL_CONFIG[reviewData.traffic_forecast || reviewData.heat_level] || HEAT_LEVEL_CONFIG['一般']).color }">{{ reviewData.traffic_forecast || reviewData.heat_level }}</span>
                </div>
              </div>
            </template>
            <p v-else class="side-empty">无审稿记录</p>
          </div>
        </div>

        <!-- 写手思路（默认不展开） -->
        <div class="side-card">
          <div class="side-title collapsible" @click="toggle('thoughts')">
            <SvgIcon name="pen" :size="14" />
            <span>写手思路</span>
            <SvgIcon :name="opened.thoughts ? 'up' : 'down'" :size="14" class="arrow" />
          </div>
          <div v-if="opened.thoughts" class="side-body">
            <MarkdownRender v-if="blog.writing_thoughts" :content="blog.writing_thoughts" />
            <p v-else class="side-empty">暂无（重新生成文章后可见）</p>
          </div>
        </div>

        <!-- 标题调研（默认不展开） -->
        <div class="side-card">
          <div class="side-title collapsible" @click="toggle('titleRes')">
            <SvgIcon name="search" :size="14" />
            <span>标题调研</span>
            <SvgIcon :name="opened.titleRes ? 'up' : 'down'" :size="14" class="arrow" />
          </div>
          <div v-if="opened.titleRes" class="side-body">
            <MarkdownRender v-if="blog.title_research" :content="cleanResearchText(blog.title_research)" />
            <p v-else class="side-empty">暂无调研数据</p>
          </div>
        </div>

        <!-- 大纲调研（默认不展开） -->
        <div class="side-card">
          <div class="side-title collapsible" @click="toggle('outlineRes')">
            <SvgIcon name="search" :size="14" />
            <span>大纲调研</span>
            <SvgIcon :name="opened.outlineRes ? 'up' : 'down'" :size="14" class="arrow" />
          </div>
          <div v-if="opened.outlineRes" class="side-body">
            <MarkdownRender v-if="blog.outline_research" :content="cleanResearchText(blog.outline_research)" />
            <p v-else class="side-empty">暂无调研数据</p>
          </div>
        </div>

        <!-- 正文调研（默认不展开） -->
        <div class="side-card">
          <div class="side-title collapsible" @click="toggle('contentRes')">
            <SvgIcon name="search" :size="14" />
            <span>正文调研</span>
            <SvgIcon :name="opened.contentRes ? 'up' : 'down'" :size="14" class="arrow" />
          </div>
          <div v-if="opened.contentRes" class="side-body">
            <template v-if="blog.content_research">
              <MarkdownRender :content="contentResearchPreview" />
              <button v-if="contentResearchLong" class="expand-btn" @click="contentResFull = !contentResFull">
                {{ contentResFull ? '收起' : '显示全部内容' }}
              </button>
            </template>
            <p v-else class="side-empty">暂无调研数据</p>
          </div>
        </div>
      </aside>
    </div>

    <el-empty v-else-if="!loading" description="文章不存在" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
import { getBlogDetail, generateContent } from '@/api/task'

const route = useRoute()
const router = useRouter()
const blogId = route.params.id

const loading = ref(false)
const blog = ref(null)
const contentResFull = ref(false)

// 侧栏卡片折叠状态（默认只展开审稿记录）
const opened = reactive({
  outline: false,
  thoughts: false,
  titleRes: false,
  outlineRes: false,
  contentRes: false,
  review: true
})

const CONTENT_RES_PREVIEW_LEN = 1500

// 无效调研结果的特征模式（旧数据中 LLM 误判或陷入循环时产生的占位内容）
const INVALID_RESEARCH_PATTERNS = [
  /请回复[您你]的具体/,
  /请提供[您你]的/,
  /待主题确认/,
  /即刻启动/,
  /收到主题后/,
  /未提供具体的/,
  /请补充该主题/,
  /I will now produce the final output/i,
  /待主題確認/,
]

function isInvalidResearch(text) {
  return INVALID_RESEARCH_PATTERNS.some(p => p.test(text))
}

/**
 * 清洗调研结果：去掉 ReAct 过程标识（思考/行动/观察），只展示最终结论
 * 策略：优先提取最后一个【总结】之后的内容；没有有效总结则去掉所有 ReAct 标记保留内容
 * 无效结果（旧数据异常）显示提示，引导重新生成
 */
function cleanResearchText(text) {
  if (!text) return ''
  let result = ''
  // 优先提取最后一个【总结】之后的内容
  const summaryIndex = text.lastIndexOf('【总结】')
  if (summaryIndex !== -1) {
    const summary = text.slice(summaryIndex + 4).trim()
    // 总结内容至少 50 字才认为有效（避免 LLM 占位式总结）
    if (summary.length > 50) {
      result = summary
    }
  }
  // 没有有效总结：去掉所有 ReAct 标记，保留内容
  if (!result) {
    result = text
      .replace(/【思考】\s*/g, '')
      .replace(/【行动】\s*/g, '')
      .replace(/【观察】\s*/g, '')
      .replace(/【总结】\s*/g, '')
      .trim()
  }
  // 无效调研结果检测：旧数据中 LLM 误判或陷入循环时产生的占位内容
  if (isInvalidResearch(result)) {
    return '（本次调研为旧数据异常，未产出有效结论。请点击页面右上角"重新生成"，生成后可查看正常调研结果。）'
  }
  return result
}

function toggle(key) {
  opened[key] = !opened[key]
}

const levelLabel = computed(() => {
  const map = {
    general: '入门（通俗易懂）',
    medium: '中等（略有专业）',
    advanced: '高级（专业深入）',
    professional: '专业（面向同行）'
  }
  return blog.value?.level ? (map[blog.value.level] || blog.value.level) : '未指定'
})

const imageSourceLabel = computed(() => {
  const map = {
    api: '联网搜图',
    ai: 'AI 生图'
  }
  return blog.value?.image_source ? (map[blog.value.image_source] || blog.value.image_source) : '未指定方式'
})

const styleLabel = computed(() => {
  const style = blog.value?.article_style
  const map = {
    popular_science: '科普类',
    technical: '技术类',
    essay: '论文类',
    prose: '散文类',
    note: '笔记类',
    custom: blog.value?.article_style_custom || '自定义',
  }
  return map[style] || style || ''
})

const wordCount = computed(() => {
  if (!blog.value?.content) return 0
  return blog.value.content.replace(/\s/g, '').length
})

const contentResearchPreview = computed(() => {
  // 先清洗 ReAct 过程，再截断
  const cleaned = cleanResearchText(blog.value?.content_research || '')
  if (!contentResFull.value && cleaned.length > CONTENT_RES_PREVIEW_LEN) {
    return cleaned.slice(0, CONTENT_RES_PREVIEW_LEN) + '\n\n……（内容较长，已截断）'
  }
  return cleaned
})

const contentResearchLong = computed(() => {
  return cleanResearchText(blog.value?.content_research || '').length > CONTENT_RES_PREVIEW_LEN
})

const reviewData = computed(() => {
  if (!blog.value?.review_feedback) return null
  const raw = blog.value.review_feedback
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch (e) {
    // 旧格式：纯文本 feedback
    return { feedback: raw }
  }
})

// 7个审稿维度的中文名
const REVIEW_DIMENSIONS = [
  { key: 'outline', label: '大纲遵从' },
  { key: 'research', label: '素材真实' },
  { key: 'relevance', label: '主旨紧扣' },
  { key: 'accuracy', label: '内容准确' },
  { key: 'logic', label: '逻辑连贯' },
  { key: 'expression', label: '表达流畅' },
  { key: 'image', label: '配图合理' },
]

// 热度预期的色温配置
const HEAT_LEVEL_CONFIG = {
  '一般': { color: '#94a3b8', bg: '#f1f5f9' },
  '中等': { color: '#3b82f6', bg: '#eff6ff' },
  '高': { color: '#22c55e', bg: '#f0fdf4' },
  '热': { color: '#f97316', bg: '#fff7ed' },
  '火爆': { color: '#ef4444', bg: '#fef2f2' },
}

function renderStars(count) {
  const n = Math.max(0, Math.min(5, count || 0))
  return '★'.repeat(n) + '☆'.repeat(5 - n)
}

async function fetchBlog() {
  loading.value = true
  try {
    blog.value = await getBlogDetail(blogId)
  } finally {
    loading.value = false
  }
}

function formatTime(timeStr) {
  if (!timeStr) return ''
  return new Date(timeStr).toLocaleString('zh-CN')
}

function copyContent() {
  const content = blog.value?.formatted_content || blog.value?.content || ''
  navigator.clipboard.writeText(content).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

async function regenerate() {
  try {
    await ElMessageBox.confirm('确定要重新生成文章吗？当前内容将被覆盖。', '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消'
    })
    await generateContent(blogId)
    ElMessage.success('重新生成任务已提交')
    router.push(`/task/${blogId}/generating`)
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

onMounted(() => {
  fetchBlog()
})
</script>

<style scoped>
.blog-detail-view {
  max-width: none;
  width: 100%;
  margin: 0 auto;
  padding: 0 40px 40px;
}

.blog-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 0;
  margin-bottom: 8px;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  background: white;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-secondary);
}

.toolbar-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.toolbar-btn.primary {
  background: var(--primary-gradient);
  border: none;
  color: white;
}

.toolbar-btn.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

/* ===== 三栏布局 =====
   以整个浏览器窗口为容器：左栏贴左、中间正文 820px 居中、右栏贴右 */
.three-column {
  display: grid;
  grid-template-columns: 360px 820px 360px;
  justify-content: space-between;
  align-items: start;
  gap: 0;
}

.left-col,
.right-col {
  width: 100%;
}

/* 中间正文列：内部保持原 820px 宽度 */
.content-col {
  min-width: 0;
}

.content-col .blog-card {
  max-width: 820px;
  margin: 0 auto;
  background: white;
  border-radius: 20px;
  box-shadow: var(--shadow-md);
  overflow: hidden;
  /* 宽屏三栏模式下：正文卡片固定高度，标题固定、内容区滚动 */
  max-height: calc(100vh + 480px);
  display: flex;
  flex-direction: column;
}

/* ===== 侧栏卡片 ===== */
.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.left-col,
.right-col {
  /* 不使用 sticky：侧栏内容可能很长，随页面自然滚动才能查看全部 */
}

.side-card {
  background: white;
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.side-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
}

.side-title.collapsible {
  cursor: pointer;
  transition: background 0.2s ease;
}

.side-title.collapsible:hover {
  background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
}

.side-title .arrow {
  margin-left: auto;
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.side-body {
  padding: 14px 16px;
  border-top: 1px solid var(--border);
  /* 展开内容超过约 20 行时，内部上下滚动查看 */
  max-height: 480px;
  overflow-y: auto;
  padding-right: 10px;
}

/* 细滚动条样式 */
.side-body::-webkit-scrollbar {
  width: 6px;
}

.side-body::-webkit-scrollbar-track {
  background: transparent;
}

.side-body::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}

.side-body::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

.selected-title {
  margin: 0;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--primary);
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
}

.config-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.config-table td {
  padding: 8px 16px;
  vertical-align: top;
  line-height: 1.6;
}

.config-table td:first-child {
  width: 76px;
  color: var(--text-muted);
  white-space: nowrap;
  font-weight: 500;
}

/* 侧栏内的 markdown 渲染：窄栏用小字号 */
.side-body :deep(.markdown-body) {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.side-body :deep(.markdown-body h1),
.side-body :deep(.markdown-body h2),
.side-body :deep(.markdown-body h3) {
  font-size: 15px;
  margin: 12px 0 8px;
  line-height: 1.4;
}

.side-body :deep(.markdown-body p) {
  margin: 8px 0;
}

.side-body :deep(.markdown-body ul),
.side-body :deep(.markdown-body ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.side-empty {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.expand-btn {
  margin-top: 10px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: 8px;
  font-size: 12px;
  color: var(--primary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.expand-btn:hover {
  border-color: var(--primary);
  background: #eef2ff;
}

/* ===== 审稿记录卡片 ===== */
.review-score-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.review-score {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.review-score .score-num {
  font-size: 36px;
  font-weight: 800;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.review-score .score-max {
  font-size: 14px;
  color: var(--text-muted);
}

.review-status {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.review-status.passed {
  background: #dcfce7;
  color: #16a34a;
}

.review-status.failed {
  background: #fee2e2;
  color: #dc2626;
}

.review-dimensions {
  margin-bottom: 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.dim-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.dim-row:last-child {
  margin-bottom: 0;
}

.dim-label {
  width: 56px;
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.dim-bar-wrap {
  flex: 1;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}

.dim-bar {
  height: 100%;
  background: var(--primary-gradient);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.dim-score {
  width: 24px;
  font-size: 11px;
  color: var(--text-secondary);
  text-align: right;
  flex-shrink: 0;
}

.review-meta {
  margin-bottom: 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.meta-row:last-child {
  margin-bottom: 0;
}

.meta-key {
  width: 56px;
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.meta-val {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
}

.meta-val.stars {
  color: #f59e0b;
  letter-spacing: 2px;
}

.heat-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.review-feedback {
  margin-bottom: 16px;
}

.feedback-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.review-suggestions {
  margin-top: 12px;
}

.suggestion-block {
  margin-bottom: 12px;
}

.suggestion-block:last-child {
  margin-bottom: 0;
}

.suggestion-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
}

.suggestion-title.issues {
  color: #dc2626;
}

.suggestion-title.suggestions {
  color: #2563eb;
}

.suggestion-block ul {
  margin: 0;
  padding-left: 18px;
}

.suggestion-block li {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 2px;
}

/* 通过理由 */
.review-pass-reasons {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border-light);
}

.pass-reasons-title {
  font-size: 12px;
  font-weight: 600;
  color: #16a34a;
  margin-bottom: 6px;
}

.pass-reasons-list {
  margin: 0;
  padding-left: 18px;
}

.pass-reasons-list li {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 3px;
}

/* 流量预测 */
.review-traffic {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border-light);
}

.traffic-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.traffic-value {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
}

.traffic-value .heat-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

/* ===== 正文区（原样式保留） ===== */
.blog-article {
  padding: 40px 48px;
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.blog-header {
  text-align: center;
  margin-bottom: 32px;
}

.blog-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 20px;
}

.blog-title {
  font-size: 32px;
  font-weight: 800;
  line-height: 1.4;
  margin: 0 0 20px;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.blog-meta {
  display: flex;
  justify-content: center;
  gap: 24px;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-muted);
}

.blog-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border), transparent);
  margin: 32px 0;
}

.blog-content {
  min-height: 300px;
  flex: 1;
  overflow-y: auto;
  padding-right: 10px;
}

/* 正文内容区细滚动条 */
.blog-content::-webkit-scrollbar {
  width: 6px;
}

.blog-content::-webkit-scrollbar-track {
  background: transparent;
}

.blog-content::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}

.blog-content::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* ===== 响应式 ===== */
/* 三栏最小需要 360+820+360 + 两侧 padding，低于 1600px 改为堆叠 */
@media (max-width: 1600px) {
  .three-column {
    grid-template-columns: 1fr;
    justify-content: center;
    gap: 24px;
  }
  .left-col,
  .right-col {
    max-width: 820px;
    margin: 0 auto;
    position: static;
    max-height: none;
    overflow: visible;
  }
  .right-col {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .right-col .side-card {
    flex: 1 1 calc(50% - 8px);
    min-width: 280px;
  }
  /* 堆叠模式下正文不限制高度，自然页面滚动 */
  .content-col .blog-card {
    max-height: none;
    display: block;
  }
  .blog-article {
    display: block;
    overflow: visible;
  }
  .blog-content {
    overflow: visible;
    padding-right: 0;
  }
}

@media (max-width: 900px) {
  .blog-detail-view {
    padding: 0 12px 32px;
  }
  .blog-article {
    padding: 24px 20px;
  }
  .blog-title {
    font-size: 24px;
  }
}
</style>
