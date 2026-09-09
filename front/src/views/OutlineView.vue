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
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
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
    await regenerateOutline(taskId)
    await fetchTask()
    ElMessage.success('大纲已重新生成')
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
</script>

<style scoped>
.outline-view {
  max-width: 800px;
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

.outline-content {
  padding: 24px;
  max-height: 500px;
  overflow-y: auto;
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
