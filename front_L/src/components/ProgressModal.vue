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
              <div class="step-name">
                {{ step.name }}
                <span v-if="getStepState(step.key) === 'done' && durations[step.key]" class="step-duration">
                  {{ durations[step.key] }}
                </span>
              </div>
              <div v-if="getStepState(step.key) === 'active' && progressText" class="step-progress">
                {{ progressText }}
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, watch, ref } from 'vue'
import SvgIcon from './SvgIcon.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  type: { type: String, default: 'titles' }, // titles / outline
  taskStatus: { type: String, default: '' },
  progressText: { type: String, default: '' }
})

const emit = defineEmits(['close'])

// 每步耗时：状态进入时记录时间戳，状态切走时算出耗时
const stepStartTimes = ref({})
const durations = ref({})

watch(() => props.taskStatus, (newStatus, oldStatus) => {
  if (newStatus === oldStatus) return
  // 上一个状态对应的步骤完成，记录耗时
  const prevStep = statusToStep(oldStatus)
  if (prevStep && stepStartTimes.value[prevStep]) {
    const cost = ((Date.now() - stepStartTimes.value[prevStep]) / 1000).toFixed(1)
    durations.value[prevStep] = cost + 's'
  }
  // 新状态对应的步骤开始计时
  const curStep = statusToStep(newStatus)
  if (curStep) {
    stepStartTimes.value[curStep] = Date.now()
  }
})

function statusToStep(status) {
  if (!status) return null
  if (props.type === 'titles') {
    const map = {
      'pending': 'create',
      'researching_title': 'research',
      'reviewing_title': 'review',
      'title_generated': 'done'
    }
    return map[status] || null
  } else if (props.type === 'outline') {
    const map = {
      'title_generated': 'submit',
      'researching_outline': 'research',
      'reviewing_outline': 'review',
      'outline_generated': 'done'
    }
    return map[status] || null
  } else {
    const map = {
      'researching_content': 'research',
      'generating_content': 'write',
      'reviewing': 'review',
      'generating_images': 'image',
      'formatting': 'image',
      'completed': 'done',
      'content_generated': 'done'
    }
    return map[status] || null
  }
}

const title = computed(() => {
  if (props.type === 'titles') return '正在生成标题'
  if (props.type === 'outline') return '正在生成大纲'
  return '正在生成正文'
})

const steps = computed(() => {
  if (props.type === 'titles') {
    return [
      { key: 'create', name: '创建任务' },
      { key: 'research', name: '调研同类文章' },
      { key: 'review', name: '审核标题' },
      { key: 'generate', name: '生成标题' }
    ]
  } else if (props.type === 'outline') {
    return [
      { key: 'submit', name: '提交配置' },
      { key: 'research', name: '调研大纲结构' },
      { key: 'review', name: '审核大纲' },
      { key: 'generate', name: '生成大纲' }
    ]
  } else {
    return [
      { key: 'research', name: '调研资料' },
      { key: 'write', name: '撰写正文' },
      { key: 'review', name: '审阅文章' },
      { key: 'image', name: '配图排版' }
    ]
  }
})

const currentStepText = computed(() => {
  const status = props.taskStatus
  if (props.type === 'titles') {
    if (status === 'pending') return '准备中...'
    if (status === 'researching_title') return '正在调研同类文章标题...'
    if (status === 'reviewing_title') return '正在审核标题质量...'
    if (status === 'title_generated') return '标题生成完成！'
    return '准备中...'
  } else if (props.type === 'outline') {
    if (status === 'title_generated') return '准备中...'
    if (status === 'researching_outline') return '正在调研同类文章大纲...'
    if (status === 'reviewing_outline') return '正在审核大纲质量...'
    if (status === 'outline_generated') return '大纲生成完成！'
    return '准备中...'
  } else {
    if (status === 'researching_content') return '正在调研正文资料...'
    if (status === 'generating_content') return '正在撰写正文...'
    if (status === 'reviewing') return '正在审阅文章质量...'
    if (status === 'generating_images') return '正在配图...'
    if (status === 'formatting') return '正在排版...'
    if (status === 'completed' || status === 'content_generated') return '正文生成完成！'
    return '准备中...'
  }
})

// 进度只进不退：记录已经到达的最大步骤索引（审稿打回时不回退）
const maxStepIdx = ref(0)

function getStepState(key) {
  const status = props.taskStatus
  let order, activeIdxMap

  if (props.type === 'titles') {
    order = ['create', 'research', 'review', 'generate']
    activeIdxMap = {
      'pending': 0, 'researching_title': 1, 'reviewing_title': 2,
      'title_generated': -1
    }
  } else if (props.type === 'outline') {
    order = ['submit', 'research', 'review', 'generate']
    activeIdxMap = {
      'title_generated': 0, 'researching_outline': 1, 'reviewing_outline': 2,
      'outline_generated': -1
    }
  } else {
    order = ['research', 'write', 'review', 'image']
    activeIdxMap = {
      'researching_content': 0, 'generating_content': 1, 'reviewing': 2,
      'generating_images': 3, 'formatting': 3,
      'completed': -1, 'content_generated': -1
    }
  }

  const activeIdx = activeIdxMap[status]
  if (activeIdx === undefined) return 'pending'
  if (activeIdx === -1) return 'done'

  // 更新最大到达步骤
  if (activeIdx > maxStepIdx.value) maxStepIdx.value = activeIdx

  const idx = order.indexOf(key)
  if (idx < maxStepIdx.value) return 'done'
  if (idx === maxStepIdx.value) return 'active'
  return 'pending'
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
  background: var(--modal-mask);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  background: var(--bg-card);
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
  background: var(--panel-gradient);
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
  background: var(--border);
  color: var(--text-muted);
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
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-duration {
  font-size: 12px;
  font-weight: 500;
  color: #059669;
  background: #d1fae5;
  padding: 1px 8px;
  border-radius: 10px;
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
  background: var(--bg-soft);
  color: var(--text-primary);
}
</style>
