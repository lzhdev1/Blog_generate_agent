<template>
  <div class="outline-view">
    <!-- 步骤条 -->
    <div class="steps-bar">
      <div class="step done"><div class="step-num">✓</div><span>创建任务</span></div>
      <div class="step-line"></div>
      <div class="step done"><div class="step-num">✓</div><span>选择标题</span></div>
      <div class="step-line"></div>
      <div class="step active"><div class="step-num">3</div><span>确认大纲</span></div>
      <div class="step-line"></div>
      <div class="step"><div class="step-num">4</div><span>生成文章</span></div>
    </div>

    <div class="two-column-layout">
      <!-- 左栏：大纲确认 -->
      <div class="left-column">
        <div class="content-card animate-fade-in-up">
          <div class="card-header">
            <div>
              <h2>确认大纲</h2>
              <p class="card-subtitle">检查文章大纲，可直接编辑修改，确认后开始生成正文</p>
            </div>
            <div class="header-actions">
              <button class="refresh-btn" @click="regenerate" :disabled="regenerating">
                <SvgIcon name="refresh" :size="16" :class="{ 'animate-spin': regenerating }" />
                <span>重新生成</span>
              </button>
              <button class="edit-btn" @click="toggleEdit" v-if="!editing">
                <SvgIcon name="edit" :size="16" />
                <span>编辑大纲</span>
              </button>
              <button class="edit-btn active" @click="toggleEdit" v-else>
                <SvgIcon name="check" :size="16" />
                <span>完成编辑</span>
              </button>
            </div>
          </div>

          <!-- 标题信息 -->
          <div class="title-banner">
            <SvgIcon name="title" :size="18" />
            <div>
              <div class="banner-label">已选标题</div>
              <div class="banner-text">{{ task?.selected_title }}</div>
            </div>
            <el-tag v-if="task?.need_image" type="warning" size="large" effect="light">
              <SvgIcon name="image" :size="14" />
              {{ task?.image_source === 'api' ? '搜索图片' : 'AI生成图片' }}
            </el-tag>
          </div>

          <!-- 大纲内容（预览模式） -->
          <div class="outline-wrapper" v-if="!editing">
            <div class="outline-header">
              <SvgIcon name="outline" :size="18" />
              <span>文章大纲</span>
              <span class="outline-tip">黄色标记为配图位置</span>
            </div>
            <div class="outline-content" v-loading="loading">
              <MarkdownRender :content="editedOutline" :highlight-image-markers="true" />
            </div>
          </div>

          <!-- 大纲内容（编辑模式） -->
          <div class="outline-wrapper" v-else>
            <div class="outline-header">
              <SvgIcon name="edit" :size="18" />
              <span>编辑大纲（Markdown 格式）</span>
              <span class="outline-tip">修改后点击"完成编辑"预览</span>
            </div>
            <div class="outline-editor">
              <el-input
                v-model="editedOutline"
                type="textarea"
                :rows="18"
                placeholder="在此编辑大纲..."
                resize="vertical"
              />
            </div>
          </div>

          <div class="actions">
            <button class="btn-secondary" @click="$router.push(`/task/${taskId}/titles`)">
              <SvgIcon name="back" :size="16" />
              返回选标题
            </button>
            <button class="btn-primary" :disabled="!editedOutline || confirming" @click="handleConfirm">
              <span v-if="!confirming">确认大纲，生成正文</span>
              <span v-else class="loading-text">
                <SvgIcon name="loading" :size="16" class="animate-spin" />
                准备中...
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- 右栏：生成配置 + 大纲调研 -->
      <div class="right-column">
        <!-- 生成配置 -->
        <div class="detail-card animate-fade-in-up">
          <div class="detail-header">
            <SvgIcon name="magic" :size="18" />
            <h3>生成配置</h3>
          </div>
          <div class="detail-body">
            <div class="config-row">
              <div class="config-label">
                <SvgIcon name="wordcount" :size="14" />
                目标字数
              </div>
              <div class="config-value">
                <el-tag size="small" effect="light">{{ task?.word_count || 500 }}字</el-tag>
              </div>
            </div>
            <div class="config-row">
              <div class="config-label">
                <SvgIcon name="level" :size="14" />
                专业水平
              </div>
              <div class="config-value">
                <el-tag size="small" effect="light" type="primary">{{ levelLabel }}</el-tag>
              </div>
            </div>
            <div class="config-row">
              <div class="config-label">
                <SvgIcon name="image" :size="14" />
                配图配置
              </div>
              <div class="config-value">
                <el-tag v-if="!task?.need_image" size="small" effect="plain" type="info">未配图</el-tag>
                <el-tag v-else-if="task?.image_source === 'api'" size="small" effect="light" type="warning">搜索图片</el-tag>
                <el-tag v-else size="small" effect="light" type="success">AI生成</el-tag>
              </div>
            </div>
            <div class="config-row extra-row">
              <div class="config-label">
                <SvgIcon name="send" :size="14" />
                额外要求
              </div>
              <div class="config-value extra-value">
                <span v-if="task?.extra_requirements">{{ task.extra_requirements }}</span>
                <span v-else class="empty-text">无</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 大纲调研 -->
        <div class="detail-card animate-fade-in-up" style="animation-delay: 0.1s">
          <div class="detail-header">
            <SvgIcon name="search" :size="18" />
            <h3>大纲调研</h3>
          </div>
          <div class="detail-body" v-if="parsedOutlineResearch">
            <div class="research-scroll">
              <div class="research-scroll-inner">
                <div class="research-section" v-if="parsedOutlineResearch.thought">
                  <div class="section-label">
                    <SvgIcon name="edit" :size="14" />
                    <span>调研方向</span>
                  </div>
                  <div class="section-content">
                    <MarkdownRender :content="parsedOutlineResearch.thought" />
                  </div>
                </div>
                <div class="research-section" v-if="parsedOutlineResearch.observation">
                  <div class="section-label">
                    <SvgIcon name="search" :size="14" />
                    <span>联网搜索发现</span>
                  </div>
                  <div class="section-content">
                    <MarkdownRender :content="parsedOutlineResearch.observation" />
                  </div>
                </div>
                <div class="research-section" v-if="parsedOutlineResearch.summary">
                  <div class="section-label">
                    <SvgIcon name="check" :size="14" />
                    <span>调研结论</span>
                  </div>
                  <div class="section-content">
                    <MarkdownRender :content="parsedOutlineResearch.summary" />
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="empty-detail" v-else>
            <SvgIcon name="search" :size="32" />
            <p>暂无调研数据</p>
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
      @close="handleModalClose"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
import ProgressModal from '@/components/ProgressModal.vue'
import { getTask, regenerateOutline, confirmOutline } from '@/api/task'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const loading = ref(false)
const regenerating = ref(false)
const confirming = ref(false)
const editing = ref(false)
const task = ref(null)
const editedOutline = ref('')

// 解析大纲调研结果（LLM返回的是【思考】【观察】【总结】格式的纯文本）
const parsedOutlineResearch = computed(() => {
  if (!task.value?.outline_research) return null
  const text = task.value.outline_research
  // 先尝试JSON解析
  try {
    const json = JSON.parse(text)
    if (json.thought || json.observation || json.summary) return json
  } catch {
    // 不是JSON，用正则提取【思考】【观察】【总结】
  }
  const thought = text.match(/【思考】([\s\S]*?)(?=【搜索】|【观察】|【总结】|$)/)?.[1]?.trim()
  const observation = text.match(/【观察】([\s\S]*?)(?=【总结】|$)/)?.[1]?.trim()
  const summary = text.match(/【总结】([\s\S]*?)$/)?.[1]?.trim()
  if (thought || observation || summary) {
    return { thought, observation, summary }
  }
  return { summary: text }
})

// 专业水平中文映射
const levelLabel = computed(() => {
  const map = {
    general: '一般',
    medium: '中等',
    advanced: '高级',
    professional: '专业'
  }
  return map[task.value?.level] || '中等'
})

// 进度弹窗相关
const showProgressModal = ref(false)
const currentTaskStatus = ref('')
const progressText = ref('')
let pollTimer = null

function startProgressPolling() {
  pollTimer = setInterval(async () => {
    try {
      const t = await getTask(taskId)
      currentTaskStatus.value = t.status
      if (t.progress) {
        progressText.value = t.progress
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

function handleModalClose() {
  // 用户点击"后台运行"，关闭弹窗但继续生成
  showProgressModal.value = false
}

async function fetchTask() {
  loading.value = true
  try {
    task.value = await getTask(taskId)
    editedOutline.value = task.value.outline || ''
  } finally {
    loading.value = false
  }
}

function toggleEdit() {
  editing.value = !editing.value
}

async function regenerate() {
  regenerating.value = true
  try {
    // 显示进度弹窗
    currentTaskStatus.value = 'title_generated'
    progressText.value = '正在重新生成大纲...'
    showProgressModal.value = true

    // 启动轮询
    startProgressPolling()

    // 异步调用重新生成大纲
    await regenerateOutline(taskId)

    // 完成后停止轮询，关闭弹窗，刷新数据
    stopProgressPolling()
    showProgressModal.value = false
    await fetchTask()
    ElMessage.success('大纲已重新生成')
  } catch (error) {
    console.error('重新生成大纲失败:', error)
    stopProgressPolling()
    showProgressModal.value = false
    ElMessage.error(error.response?.data?.detail || '重新生成大纲失败')
  } finally {
    regenerating.value = false
  }
}

async function handleConfirm() {
  if (!editedOutline.value.trim()) {
    ElMessage.warning('大纲不能为空')
    return
  }
  confirming.value = true
  try {
    // 传入编辑后的大纲
    await confirmOutline(taskId, editedOutline.value)
    ElMessage.success('大纲已确认，正在生成正文...')
    router.push(`/task/${taskId}/generating`)
  } finally {
    confirming.value = false
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
.outline-view {
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
  flex: 1.4;
  min-width: 0;
}

.right-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
  align-self: stretch;
}

/* 右栏卡片 */
.detail-card {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.right-column .detail-card:last-child .detail-body {
  padding: 16px 20px 20px;
}

.research-scroll {
  max-height: 460px;
  overflow-y: auto;
  border: 1px solid #f0f0f5;
  border-radius: 10px;
  background: #fafafc;
}

.research-scroll-inner {
  padding: 14px 16px 20px;
}

/* 调研区块 */
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
  color: #667eea;
  margin-bottom: 8px;
}

.section-content {
  font-size: 13px;
  color: #444;
  line-height: 1.7;
  padding-left: 20px;
}

.section-content :deep(p) {
  margin: 0 0 8px 0;
}

.section-content :deep(p:last-child) {
  margin-bottom: 0;
}

.section-content :deep(ul),
.section-content :deep(ol) {
  margin: 0;
  padding-left: 20px;
}

.section-content :deep(li) {
  margin-bottom: 4px;
}

.section-content :deep(strong) {
  color: #667eea;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid #f0f0f5;
  color: #667eea;
}

.detail-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1a1a2e;
}

.detail-body {
  padding: 16px 20px 20px;
}

/* 配置行 */
.config-row {
  display: flex;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f5f5fa;
}

.config-row:last-child {
  border-bottom: none;
}

.config-label {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 90px;
  font-size: 13px;
  color: #888;
  flex-shrink: 0;
}

.config-value {
  flex: 1;
}

.extra-row {
  align-items: flex-start;
}

.extra-value {
  font-size: 13px;
  color: #333;
  line-height: 1.6;
}

.empty-text {
  color: #bbb;
  font-style: italic;
}

.empty-detail {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: #ccc;
  gap: 12px;
}

.empty-detail p {
  margin: 0;
  font-size: 14px;
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
  width: 60px;
  height: 2px;
  background: #e2e8f0;
  margin: 0 8px;
  margin-bottom: 22px;
}

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

.header-actions {
  display: flex;
  gap: 8px;
}

.refresh-btn,
.edit-btn {
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

.refresh-btn:hover:not(:disabled),
.edit-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.edit-btn.active {
  background: var(--primary-gradient);
  border: none;
  color: white;
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.title-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  background: linear-gradient(135deg, #f5f3ff 0%, #eef2ff 100%);
  border-radius: 14px;
  margin-bottom: 24px;
}

.title-banner > svg {
  color: var(--primary);
}

.banner-label {
  font-size: 12px;
  color: var(--text-muted);
}

.banner-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-top: 2px;
}

.title-banner .el-tag {
  margin-left: auto;
}

.outline-wrapper {
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 28px;
}

.outline-content {
  padding: 24px;
  max-height: 500px;
  overflow-y: auto;
}

.outline-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  background: #f8fafc;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  font-size: 14px;
}

.outline-tip {
  margin-left: auto;
  font-size: 12px;
  color: var(--warning);
  font-weight: 400;
}

.outline-editor {
  padding: 16px;
}

.outline-editor :deep(.el-textarea__inner) {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 14px;
  line-height: 1.7;
  border: none;
  box-shadow: none !important;
}

.actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 6px;
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
  display: flex;
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
</style>
