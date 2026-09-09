<template>
  <div class="titles-view">
    <!-- 步骤条 -->
    <div class="steps-bar">
      <div class="step" :class="{ active: step >= 1, done: step > 1 }">
        <div class="step-num">1</div>
        <span>创建任务</span>
      </div>
      <div class="step-line"></div>
      <div class="step" :class="{ active: step >= 2, done: step > 2 }">
        <div class="step-num">2</div>
        <span>选择标题</span>
      </div>
      <div class="step-line"></div>
      <div class="step" :class="{ active: step >= 3, done: step > 3 }">
        <div class="step-num">3</div>
        <span>确认大纲</span>
      </div>
      <div class="step-line"></div>
      <div class="step" :class="{ active: step >= 4 }">
        <div class="step-num">4</div>
        <span>生成文章</span>
      </div>
    </div>

    <div class="two-column-layout">
      <!-- 左栏：标题选择 -->
      <div class="left-column">
        <div class="content-card animate-fade-in-up">
          <div class="card-header">
            <div>
              <h2>选择标题</h2>
              <p class="card-subtitle">AI 为你生成了 3 个标题，选择一个继续</p>
            </div>
            <button class="refresh-btn" @click="regenerateTitles" :disabled="regenerating">
              <SvgIcon name="refresh" :size="16" :class="{ 'animate-spin': regenerating }" />
              <span>重新生成</span>
            </button>
          </div>

          <div class="topic-banner">
            <SvgIcon name="edit" :size="18" />
            <span class="topic-label">主题：</span>
            <span class="topic-text">{{ task?.topic }}</span>
          </div>

          <!-- 标题列表 -->
          <div class="titles-list">
            <div
              v-for="(title, index) in task?.titles || []"
              :key="index"
              class="title-card"
              :class="{ selected: selectedTitle === title }"
              @click="selectTitle(title)"
            >
              <div class="title-number">{{ index + 1 }}</div>
              <div class="title-content">
                <input
                  v-if="editingIndex === index"
                  v-model="editingTitle"
                  class="title-input"
                  @click.stop
                  @blur="confirmEdit(index)"
                  @keyup.enter="confirmEdit(index)"
                  @keyup.esc="cancelEdit"
                  ref="titleInput"
                />
                <h3 v-else>{{ title }}</h3>
              </div>
              <div class="title-actions" v-if="selectedTitle === title">
                <button class="edit-btn" @click.stop="startEdit(index)" title="编辑标题">
                  <SvgIcon name="edit" :size="16" />
                </button>
                <div class="title-check">
                  <SvgIcon name="check" :size="20" />
                </div>
              </div>
            </div>
          </div>

          <!-- 配图配置 -->
          <div class="config-section">
            <h3 class="config-title">
              <SvgIcon name="image" :size="18" />
              配图配置
            </h3>
            <div class="config-row">
              <div class="config-label">
                <span>是否需要配图</span>
                <span class="config-desc">在大纲中标注配图位置，生成正文后自动配图</span>
              </div>
              <div class="switch-wrapper" @click="needImage = !needImage">
                <div class="switch-track" :class="{ on: needImage }">
                  <div class="switch-thumb"></div>
                </div>
              </div>
            </div>
            <div class="config-row image-source" v-if="needImage">
              <div class="config-label">
                <span>配图方式</span>
              </div>
              <div class="source-options">
                <div
                  class="source-option"
                  :class="{ active: imageSource === 'api' }"
                  @click="imageSource = 'api'"
                >
                  <SvgIcon name="search" :size="20" />
                  <div>
                    <div class="option-title">搜索图片</div>
                    <div class="option-desc">Pexels / Unsplash 正版图片</div>
                  </div>
                </div>
                <div
                  class="source-option"
                  :class="{ active: imageSource === 'ai' }"
                  @click="imageSource = 'ai'"
                >
                  <SvgIcon name="magic" :size="20" />
                  <div>
                    <div class="option-title">AI 生成</div>
                    <div class="option-desc">通义万相 AI 绘画</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="actions">
            <button class="btn-secondary" @click="$router.push('/')">返回列表</button>
            <button
              class="btn-primary"
              :disabled="!selectedTitle || submitting"
              @click="handleSubmit"
            >
              <span v-if="!submitting">确认选择，生成大纲</span>
              <span v-else class="loading-text">
                <SvgIcon name="loading" :size="16" class="animate-spin" />
                生成中...
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- 右栏：调研详情 + 标题评分 -->
      <div class="right-column">
        <!-- 调研过程 -->
        <div class="detail-card animate-fade-in-up">
          <div class="detail-header">
            <SvgIcon name="search" :size="18" />
            <h3>调研过程</h3>
          </div>
          <div class="detail-body" v-if="parsedResearch">
            <div class="research-section" v-if="parsedResearch.thought">
              <div class="section-label">
                <SvgIcon name="edit" :size="14" />
                <span>调研方向</span>
              </div>
              <p class="section-content">{{ parsedResearch.thought }}</p>
            </div>
            <div class="research-section" v-if="parsedResearch.observation">
              <div class="section-label">
                <SvgIcon name="search" :size="14" />
                <span>联网搜索发现</span>
              </div>
              <p class="section-content">{{ parsedResearch.observation }}</p>
            </div>
            <div class="research-section" v-if="parsedResearch.summary">
              <div class="section-label">
                <SvgIcon name="check" :size="14" />
                <span>调研结论</span>
              </div>
              <p class="section-content">{{ parsedResearch.summary }}</p>
            </div>
          </div>
          <div class="empty-detail" v-else>
            <SvgIcon name="search" :size="32" />
            <p>暂无调研数据</p>
          </div>
        </div>

        <!-- 标题评分 -->
        <div class="detail-card animate-fade-in-up" style="animation-delay: 0.1s">
          <div class="detail-header">
            <SvgIcon name="review" :size="18" />
            <h3>标题评分</h3>
          </div>
          <div class="detail-body" v-if="task?.title_scores?.length">
            <div
              v-for="(score, index) in task.title_scores"
              :key="index"
              class="score-card"
              :class="{ selected: selectedTitle === score.title }"
            >
              <div class="score-header">
                <span class="score-index">{{ index + 1 }}</span>
                <span class="score-total">{{ score.total }}分</span>
              </div>
              <div class="score-bars">
                <div class="score-bar-item">
                  <span class="bar-label">准确性</span>
                  <div class="bar-track">
                    <div class="bar-fill" :style="{ width: (score.accuracy || 0) * 10 + '%' }"></div>
                  </div>
                  <span class="bar-value">{{ score.accuracy }}</span>
                </div>
                <div class="score-bar-item">
                  <span class="bar-label">独特性</span>
                  <div class="bar-track">
                    <div class="bar-fill uniqueness" :style="{ width: (score.uniqueness || 0) * 10 + '%' }"></div>
                  </div>
                  <span class="bar-value">{{ score.uniqueness }}</span>
                </div>
                <div class="score-bar-item">
                  <span class="bar-label">SEO</span>
                  <div class="bar-track">
                    <div class="bar-fill seo" :style="{ width: (score.seo || 0) * 10 + '%' }"></div>
                  </div>
                  <span class="bar-value">{{ score.seo }}</span>
                </div>
              </div>
              <div class="score-pros-cons" v-if="score.pros?.length || score.cons?.length">
                <div class="pros" v-if="score.pros?.length">
                  <span class="tag pro">优点</span>
                  <span v-for="(p, i) in score.pros" :key="i" class="tag-text">{{ p }}</span>
                </div>
                <div class="cons" v-if="score.cons?.length">
                  <span class="tag con">缺点</span>
                  <span v-for="(c, i) in score.cons" :key="i" class="tag-text">{{ c }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="empty-detail" v-else>
            <SvgIcon name="review" :size="32" />
            <p>暂无评分数据</p>
            <p class="empty-hint">重新生成标题后会显示评分</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 进度弹窗 -->
    <ProgressModal
      :visible="showProgressModal"
      type="outline"
      :task-status="currentTaskStatus"
      :progress-text="progressText"
      @close="showProgressModal = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import ProgressModal from '@/components/ProgressModal.vue'
import { getTask, generateTitles, submitTitleConfig } from '@/api/task'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id
const step = 2

const loading = ref(false)
const regenerating = ref(false)
const submitting = ref(false)
const task = ref(null)
const selectedTitle = ref('')
const needImage = ref(false)
const imageSource = ref('api')
const progressText = ref('')
const showProgressModal = ref(false)
const currentTaskStatus = ref('')
const editingIndex = ref(-1)
const editingTitle = ref('')
const titleInput = ref(null)
let pollTimer = null

// 解析调研结果（ReAct格式）
const parsedResearch = computed(() => {
  if (!task.value?.title_research) return null
  const text = task.value.title_research
  const result = { thought: '', observation: '', summary: '' }

  // 提取【思考】部分
  const thoughtMatch = text.match(/【思考】([\s\S]*?)(?=【搜索】|【观察】|【总结】|$)/)
  if (thoughtMatch) result.thought = thoughtMatch[1].trim()

  // 提取【观察】部分
  const obsMatch = text.match(/【观察】([\s\S]*?)(?=【总结】|$)/)
  if (obsMatch) result.observation = obsMatch[1].trim()

  // 提取【总结】部分
  const sumMatch = text.match(/【总结】([\s\S]*?)$/)
  if (sumMatch) result.summary = sumMatch[1].trim()

  // 如果没有匹配到ReAct格式，把全文作为summary
  if (!result.thought && !result.observation && !result.summary) {
    result.summary = text
  }
  return result
})

function stopProgressPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startProgressPolling() {
  pollTimer = setInterval(async () => {
    try {
      const t = await getTask(taskId)
      currentTaskStatus.value = t.status
      if (t.progress) {
        progressText.value = t.progress
      }
      if (t.status === 'outline_generated') {
        stopProgressPolling()
        showProgressModal.value = false
        submitting.value = false
        router.push(`/task/${taskId}/outline`)
      }
      if (t.status === 'failed') {
        stopProgressPolling()
        showProgressModal.value = false
        submitting.value = false
        ElMessage.error(t.error || '生成大纲失败')
      }
    } catch (e) {
      console.error('轮询进度失败:', e)
    }
  }, 1500)
}

async function fetchTask() {
  loading.value = true
  try {
    task.value = await getTask(taskId)
    console.log('[调试] 任务数据:', {
      taskId: taskId,
      titlesCount: task.value.titles?.length || 0,
      titleScores: task.value.title_scores,
      titleScoresType: typeof task.value.title_scores,
      titleScoresLength: task.value.title_scores?.length
    })
    if (task.value.titles?.length) {
      selectedTitle.value = task.value.titles[0]
    }
    if (task.value.need_image) {
      needImage.value = true
      imageSource.value = task.value.image_source || 'api'
    }
  } finally {
    loading.value = false
  }
}

function selectTitle(title) {
  if (editingIndex.value >= 0) return
  selectedTitle.value = title
}

function startEdit(index) {
  editingIndex.value = index
  editingTitle.value = task.value.titles[index]
  setTimeout(() => {
    if (titleInput.value && titleInput.value[0]) {
      titleInput.value[0].focus()
      titleInput.value[0].select()
    }
  }, 50)
}

function confirmEdit(index) {
  if (editingTitle.value.trim()) {
    task.value.titles[index] = editingTitle.value.trim()
    selectedTitle.value = editingTitle.value.trim()
  }
  editingIndex.value = -1
}

function cancelEdit() {
  editingIndex.value = -1
}

async function regenerateTitles() {
  regenerating.value = true
  try {
    await generateTitles(taskId)
    await fetchTask()
    ElMessage.success('标题已重新生成')
  } finally {
    regenerating.value = false
  }
}

async function handleSubmit() {
  if (!selectedTitle.value) {
    ElMessage.warning('请选择一个标题')
    return
  }
  submitting.value = true
  progressText.value = '正在提交配置...'
  currentTaskStatus.value = 'title_generated'
  showProgressModal.value = true
  try {
    await submitTitleConfig(taskId, {
      title: selectedTitle.value,
      need_image: needImage.value,
      image_source: needImage.value ? imageSource.value : null
    })
    startProgressPolling()
  } catch (error) {
    console.error('提交配置失败:', error)
    submitting.value = false
    showProgressModal.value = false
    ElMessage.error('提交配置失败')
  }
}

onMounted(() => {
  fetchTask()
})

onUnmounted(() => {
  stopProgressPolling()
})
</script>

<style scoped>
.titles-view {
  max-width: 1200px;
  margin: 0 auto;
}

/* 两栏布局 */
.two-column-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

.left-column {
  flex: 1;
  min-width: 0;
}

.right-column {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

@media (max-width: 960px) {
  .two-column-layout {
    flex-direction: column;
  }
  .right-column {
    width: 100%;
  }
}

/* 步骤条 */
.steps-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 32px;
  padding: 0 20px;
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
  transition: all 0.3s ease;
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
  width: 60px;
  height: 2px;
  background: #e2e8f0;
  margin: 0 8px;
  margin-bottom: 22px;
}

/* 内容卡片 */
.content-card {
  background: white;
  border-radius: 20px;
  padding: 32px;
  box-shadow: var(--shadow-md);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.card-header h2 {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 700;
}

.card-subtitle {
  margin: 0;
  font-size: 14px;
  color: var(--text-muted);
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  background: white;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  transition: all 0.2s ease;
}

.refresh-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 主题横幅 */
.topic-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  background: linear-gradient(135deg, #f5f3ff 0%, #eef2ff 100%);
  border-radius: 12px;
  margin-bottom: 24px;
  color: var(--primary-dark);
}

.topic-label {
  font-size: 13px;
  opacity: 0.7;
}

.topic-text {
  font-weight: 500;
  font-size: 14px;
}

/* 标题卡片 */
.titles-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 28px;
}

.title-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border: 2px solid var(--border);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
}

.title-card:hover {
  border-color: var(--primary-light);
  background: #fafaff;
}

.title-card.selected {
  border-color: var(--primary);
  background: linear-gradient(135deg, #f5f3ff 0%, #eef2ff 100%);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.15);
}

.title-number {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.title-card.selected .title-number {
  background: var(--primary-gradient);
  color: white;
}

.title-content {
  flex: 1;
}

.title-content h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
}

.title-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.edit-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: white;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.edit-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: #f5f3ff;
}

.title-check {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.title-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--primary);
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  outline: none;
  background: white;
}

/* 配置区域 */
.config-section {
  background: #f8fafc;
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 28px;
}

.config-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.config-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
}

.config-row + .config-row {
  border-top: 1px solid var(--border);
}

.config-label span {
  font-size: 14px;
  font-weight: 500;
}

.config-desc {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
  font-weight: 400 !important;
}

/* 开关 */
.switch-wrapper {
  cursor: pointer;
}

.switch-track {
  width: 48px;
  height: 26px;
  border-radius: 13px;
  background: #cbd5e1;
  position: relative;
  transition: all 0.3s ease;
}

.switch-track.on {
  background: var(--primary);
}

.switch-thumb {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: white;
  position: absolute;
  top: 2px;
  left: 2px;
  transition: all 0.3s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.switch-track.on .switch-thumb {
  left: 24px;
}

/* 配图方式 */
.image-source {
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}

.source-options {
  display: flex;
  gap: 12px;
  width: 100%;
}

.source-option {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 2px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.source-option:hover {
  border-color: var(--primary-light);
}

.source-option.active {
  border-color: var(--primary);
  background: #f5f3ff;
}

.option-title {
  font-size: 14px;
  font-weight: 600;
}

.option-desc {
  font-size: 12px;
  color: var(--text-muted);
}

/* 按钮 */
.actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn-secondary {
  padding: 12px 24px;
  border: 1px solid var(--border);
  background: white;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  border-color: var(--text-muted);
}

.btn-primary {
  padding: 12px 28px;
  border: none;
  background: var(--primary-gradient);
  color: white;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.loading-text {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 右侧详情卡片 */
.detail-card {
  background: white;
  border-radius: 16px;
  box-shadow: var(--shadow-md);
  overflow: hidden;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
}

.detail-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-body {
  padding: 16px 20px;
  max-height: 400px;
  overflow-y: auto;
}

/* 调研部分 */
.research-section {
  margin-bottom: 16px;
}

.research-section:last-child {
  margin-bottom: 0;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  margin-bottom: 8px;
}

.section-content {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.empty-detail {
  padding: 40px 20px;
  text-align: center;
  color: var(--text-muted);
}

.empty-detail p {
  margin: 8px 0 0;
  font-size: 13px;
}

.empty-hint {
  font-size: 12px !important;
  opacity: 0.7;
}

/* 评分卡片 */
.score-card {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 12px;
  transition: all 0.2s ease;
}

.score-card:last-child {
  margin-bottom: 0;
}

.score-card.selected {
  border-color: var(--primary);
  background: linear-gradient(135deg, #f5f3ff 0%, #eef2ff 100%);
}

.score-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.score-index {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}

.score-card.selected .score-index {
  background: var(--primary-gradient);
  color: white;
}

.score-total {
  font-size: 18px;
  font-weight: 800;
  color: var(--primary);
}

.score-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.score-bar-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bar-label {
  width: 40px;
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 6px;
  background: #f1f5f9;
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--primary-gradient);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.bar-fill.uniqueness {
  background: linear-gradient(90deg, #10b981, #059669);
}

.bar-fill.seo {
  background: linear-gradient(90deg, #f59e0b, #d97706);
}

.bar-value {
  width: 20px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: right;
}

.score-pros-cons {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pros, .cons {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
}

.tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.tag.pro {
  background: #d1fae5;
  color: #059669;
}

.tag.con {
  background: #fee2e2;
  color: #dc2626;
}

.tag-text {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
}
</style>
