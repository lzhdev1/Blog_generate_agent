<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-mask" @click.self="handleClose">
      <div class="modal-card animate-fade-in-up">
        <div class="modal-header">
          <div class="modal-icon">
            <SvgIcon name="magic" :size="24" />
          </div>
          <div>
            <h3>{{ title }}</h3>
            <p class="modal-subtitle">{{ currentStepText }}</p>
          </div>
        </div>

        <div class="steps-list">
          <div
            v-for="(step, index) in steps"
            :key="step.key"
            class="step-item"
            :class="getStepClass(step.key)"
          >
            <div class="step-icon">
              <SvgIcon v-if="getStepState(step.key) === 'done'" name="check" :size="16" />
              <SvgIcon v-else-if="getStepState(step.key) === 'active'" name="loading" :size="16" class="animate-spin" />
              <span v-else class="step-num">{{ index + 1 }}</span>
            </div>
            <div class="step-info">
              <div class="step-name">{{ step.name }}</div>
              <div v-if="getStepState(step.key) === 'active' && progressText" class="step-progress">
                {{ progressText }}
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-text" @click="handleClose">后台运行</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import SvgIcon from './SvgIcon.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  type: { type: String, default: 'titles' }, // titles / outline
  taskStatus: { type: String, default: '' },
  progressText: { type: String, default: '' }
})

const emit = defineEmits(['close'])

const title = computed(() => {
  return props.type === 'titles' ? '正在生成标题' : '正在生成大纲'
})

const steps = computed(() => {
  if (props.type === 'titles') {
    return [
      { key: 'create', name: '创建任务' },
      { key: 'research', name: '调研同类文章' },
      { key: 'generate', name: '生成标题' }
    ]
  } else {
    return [
      { key: 'submit', name: '提交配置' },
      { key: 'research', name: '调研大纲结构' },
      { key: 'generate', name: '生成大纲' }
    ]
  }
})

const currentStepText = computed(() => {
  const status = props.taskStatus
  if (props.type === 'titles') {
    if (status === 'pending') return '准备中...'
    if (status === 'researching_title') return '正在调研同类文章标题...'
    if (status === 'generating_titles') return '正在生成标题并评估...'
    if (status === 'title_generated') return '标题生成完成！'
    return '准备中...'
  } else {
    if (status === 'title_generated') return '准备中...'
    if (status === 'researching_outline') return '正在调研同类文章大纲...'
    if (status === 'generating_outline') return '正在生成大纲...'
    if (status === 'outline_generated') return '大纲生成完成！'
    return '准备中...'
  }
})

function getStepState(key) {
  const status = props.taskStatus
  if (props.type === 'titles') {
    const order = ['create', 'research', 'generate']
    const currentIdx = {
      'pending': 0,
      'researching_title': 1,
      'generating_titles': 2,
      'title_generated': 3
    }[status] ?? 0
    const idx = order.indexOf(key)
    if (idx < currentIdx) return 'done'
    if (idx === currentIdx) return 'active'
    return 'pending'
  } else {
    const order = ['submit', 'research', 'generate']
    const currentIdx = {
      'title_generated': 0,
      'researching_outline': 1,
      'generating_outline': 2,
      'outline_generated': 3
    }[status] ?? 0
    const idx = order.indexOf(key)
    if (idx < currentIdx) return 'done'
    if (idx === currentIdx) return 'active'
    return 'pending'
  }
}

function getStepClass(key) {
  return `step-${getStepState(key)}`
}

function handleClose() {
  emit('close')
}
</script>

<style scoped>
.modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  background: white;
  border-radius: 20px;
  padding: 32px;
  width: 420px;
  max-width: 90vw;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}

.modal-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: var(--primary-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}

.modal-header h3 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 700;
}

.modal-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--primary);
  font-weight: 500;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 12px;
  border-radius: 12px;
  transition: all 0.3s ease;
}

.step-item.step-active {
  background: linear-gradient(135deg, #f5f3ff 0%, #eef2ff 100%);
}

.step-item.step-done {
  opacity: 0.7;
}

.step-item.step-pending {
  opacity: 0.4;
}

.step-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: 600;
  font-size: 14px;
}

.step-pending .step-icon {
  background: #e2e8f0;
  color: #94a3b8;
}

.step-active .step-icon {
  background: var(--primary-gradient);
  color: white;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.3);
}

.step-done .step-icon {
  background: #d1fae5;
  color: #059669;
}

.step-info {
  flex: 1;
  padding-top: 4px;
}

.step-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.step-pending .step-name {
  color: var(--text-muted);
}

.step-progress {
  font-size: 12px;
  color: var(--primary);
  margin-top: 4px;
}

.modal-footer {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

.btn-text {
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.btn-text:hover {
  background: #f1f5f9;
  color: var(--text-primary);
}
</style>
