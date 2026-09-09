<template>
  <div class="create-view">
    <div class="create-card animate-fade-in-up">
      <div class="create-header">
        <div class="create-icon">
          <SvgIcon name="edit" :size="32" />
        </div>
        <h1>创建新博客</h1>
        <p>输入你想写的主题，AI 将帮你完成全文创作</p>
      </div>

      <div class="input-wrapper">
        <SvgIcon name="edit" :size="22" class="input-icon" />
        <el-input
          v-model="topic"
          type="textarea"
          :rows="3"
          placeholder="例如：Python 快速入门指南、Vue 3 组合式 API 最佳实践..."
          resize="none"
        />
      </div>

      <div class="examples">
        <span class="examples-label">热门主题：</span>
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

      <div class="actions">
        <button class="btn-secondary" @click="$router.push('/')">返回</button>
        <button class="btn-primary" :disabled="!topic.trim() || creating" @click="handleCreate">
          <span v-if="!creating">
            <SvgIcon name="send" :size="16" />
            开始生成
          </span>
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
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import { createTask, generateTitles } from '@/api/task'

const router = useRouter()
const topic = ref('')
const creating = ref(false)

const examples = [
  'Python 快速入门指南',
  'Vue 3 组合式 API 最佳实践',
  'Docker 容器化部署实战',
  'FastAPI 高性能后端开发'
]

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
</script>

<style scoped>
.create-view {
  max-width: 640px;
  margin: 40px auto;
}

.create-card {
  background: white;
  border-radius: 24px;
  padding: 48px 40px;
  box-shadow: var(--shadow-lg);
}

.create-header {
  text-align: center;
  margin-bottom: 32px;
}

.create-icon {
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

.create-header h1 {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 700;
}

.create-header p {
  margin: 0;
  color: var(--text-muted);
  font-size: 15px;
}

.input-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border: 2px solid var(--border);
  border-radius: 16px;
  margin-bottom: 20px;
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: var(--primary);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.15);
}

.input-icon {
  color: var(--primary);
  margin-top: 8px;
  flex-shrink: 0;
}

.input-wrapper :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none !important;
  font-size: 15px;
  padding: 8px 0;
  resize: none;
}

.examples {
  margin-bottom: 28px;
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
  margin-top: 10px;
}

.example-tag {
  padding: 6px 14px;
  background: #f8fafc;
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
