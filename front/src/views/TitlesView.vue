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
          @click="selectedTitle = title"
        >
          <div class="title-number">{{ index + 1 }}</div>
          <div class="title-content">
            <h3>{{ title }}</h3>
          </div>
          <div class="title-check" v-if="selectedTitle === title">
            <SvgIcon name="check" :size="20" />
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
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
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

async function fetchTask() {
  loading.value = true
  try {
    task.value = await getTask(taskId)
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
  try {
    await submitTitleConfig(taskId, {
      title: selectedTitle.value,
      need_image: needImage.value,
      image_source: needImage.value ? imageSource.value : null
    })
    ElMessage.success('配置已提交，正在生成大纲...')
    router.push(`/task/${taskId}/outline`)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchTask()
})
</script>

<style scoped>
.titles-view {
  max-width: 720px;
  margin: 0 auto;
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
</style>
