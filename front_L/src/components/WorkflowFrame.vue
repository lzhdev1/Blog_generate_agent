<template>
  <div class="wf-page">
    <header class="wf-header">
      <div>
        <h1>{{ t(stage + 'Head') }}</h1>
        <p>{{ t(stage + 'Intro') }}</p>
      </div>
      <router-link to="/my-articles" class="wf-library"><SvgIcon name="back" :size="15" />{{ t('library') }}</router-link>
    </header>
    <ol class="wf-stages" :aria-label="t('workflow')">
      <li v-for="(key, index) in stages" :key="key"
        :class="{ 'wf-past': index < position, 'wf-current': index === position }"
        :aria-current="index === position ? 'step' : undefined">
        <span class="wf-stage-mark"><SvgIcon v-if="index < position" name="check" :size="13" /><template v-else>{{ index + 1 }}</template></span>
        <span>{{ t(key) }}</span>
      </li>
    </ol>
    <div v-if="admission || (error && !pending)" class="wf-notice" role="alert">
      <div><strong>{{ t(admission ? 'notQueued' : 'serverError') }}</strong><p>{{ admission?.message || error }}</p>
        <p v-if="retryTime">{{ t('retryAfter', { time: retryTime }) }}</p></div>
      <button type="button" class="wf-secondary" :disabled="busy" @click="$emit('reload')">{{ t('reconnect') }}</button>
    </div>
    <section v-if="!task && !error" class="wf-panel wf-loading" role="status">{{ t('loading') }}</section>
    <div v-if="task" class="wf-layout">
      <div class="wf-stack">
        <div v-if="pending" class="wf-panel wf-ready" role="status">
          <h2>{{ t(busy ? 'workingAction' : 'unconfirmedSubmission') }}</h2>
          <p>{{ t('replayHint') }}</p>
          <p v-if="pendingChanged">{{ t('originalSettings') }}</p>
          <p v-if="error">{{ error }}</p>
          <div class="wf-recovery-actions">
            <button type="button" class="wf-primary" :disabled="busy" @click="$emit('replay')">{{ t('replayRequest') }}</button>
            <button type="button" class="wf-secondary" :disabled="busy" @click="$emit('reload')">{{ t('refreshStatus') }}</button>
          </div>
        </div>
        <div v-if="task.status === 'failed'" class="wf-panel wf-failure" role="alert">
          <h2>{{ t('failed') }}</h2>
          <p>{{ task.error || task.progress }}</p>
          <div class="wf-recovery-actions">
            <button v-if="!pending" type="button" class="wf-primary" :disabled="busy || quota.insufficient(costStage)" @click="$emit('retry')">{{ retryLabel }}</button>
            <button v-if="task.can_restore_previous" type="button" class="wf-secondary" :disabled="busy || !!pending" @click="$emit('restore')">{{ t('restorePrevious') }}</button>
            <slot v-if="!pending" name="recovery-actions" />
          </div>
          <p v-if="task.can_restore_previous">{{ t('restoreHint') }}</p>
        </div>
        <slot v-if="pending || task.status === 'failed'" name="failed-draft" />
        <div v-else-if="task.job?.status === 'queued' && activeTaskStates.has(task.status)" class="wf-panel wf-ready" role="status">
          <div class="wf-panel-head"><h2>{{ t('inQueue') }}</h2><SvgIcon name="clock" :size="19" /></div>
          <p>{{ t('queueHint') }}</p>
          <p v-if="task.progress">{{ task.progress }}</p>
        </div>
        <WorkflowProgress v-else-if="activeTaskStates.has(task.status)" :type="stage"
          :task-status="task.status" :progress-text="task.progress || ''" :need-image="task.need_image" />
        <template v-else>
          <p v-if="task.progress && ['title_generated', 'outline_generated'].includes(task.status)" class="wf-handoff" role="status">
            <SvgIcon name="review" :size="17" /><span>{{ task.progress }}</span>
          </p>
          <ReviewFindings v-if="task.review_result?.passed === false && ((stage === 'titles' && task.review_result.stage === 'title') || (stage === 'outline' && task.review_result.stage === 'outline'))" :report="task.review_result" />
          <slot />
        </template>
        <button v-if="activeTaskStates.has(task.status) && !error" type="button" class="wf-text-btn wf-refresh" :disabled="busy" @click="$emit('reload')">{{ t('refreshStatus') }}</button>
      </div>
      <aside class="wf-stack">
        <GenerationAllowance class="wf-panel" :stage="activeTaskStates.has(task.status) ? undefined : costStage" />
        <section class="wf-panel wf-brief">
          <div class="wf-panel-head"><h2>{{ t('brief') }}</h2><span class="wf-id">#{{ task.id }}</span></div>
          <dl>
            <dt>{{ t('topic') }}</dt><dd>{{ task.topic }}</dd>
            <template v-if="task.purpose"><dt>{{ t('purpose') }}</dt><dd>{{ task.purpose }}</dd></template>
            <template v-if="task.level"><dt>{{ t('audience') }}</dt><dd>{{ t(task.level) }}</dd></template>
            <template v-if="task.selected_title"><dt>{{ t('chosenTitle') }}</dt><dd>{{ task.selected_title }}</dd></template>
            <template v-if="task.article_style"><dt>{{ t('style') }}</dt><dd>{{ task.article_style === 'custom' ? task.article_style_custom : t(task.article_style) }}</dd></template>
            <template v-if="task.word_count"><dt>{{ t('target') }}</dt><dd>{{ t('wordUnit', { count: task.word_count }) }}</dd></template>
            <template v-if="task.extra_requirements"><dt>{{ t('outlineReq') }}</dt><dd>{{ task.extra_requirements }}</dd></template>
          </dl>
        </section>
        <slot name="aside" />
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import SvgIcon from './SvgIcon.vue'
import WorkflowProgress from './WorkflowProgress.vue'
import GenerationAllowance from './GenerationAllowance.vue'
import ReviewFindings from './ReviewFindings.vue'
import { useQuotaStore } from '@/stores/quota'
import { useWorkflowText } from '@/i18n/workflow'
import { activeTaskStates } from '@/utils/taskWorkflow'
import { pendingGeneration } from '@/api/task'
import '@/assets/styles/workflow.css'

const props = defineProps({
  stage: { type: String, required: true }, task: Object, error: String, busy: Boolean
})
defineEmits(['reload', 'retry', 'replay', 'restore'])
const { t, locale } = useWorkflowText()
const quota = useQuotaStore()
const pending = computed(() => props.task && !activeTaskStates.has(props.task.status) && pendingGeneration(props.task.id))
const pendingChanged = computed(() => pending.value && (pending.value.status !== props.task.status ||
  Boolean(pending.value.updatedAt && pending.value.updatedAt !== props.task.updated_at)))
const admission = computed(() => quota.rejection && String(quota.rejection.taskId) === String(props.task?.id) && !activeTaskStates.has(props.task?.status) ? quota.rejection : null)
const retryTime = computed(() => admission.value?.retryAt ? new Intl.DateTimeFormat(locale.value, { month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit' }).format(admission.value.retryAt) : '')
const costStage = computed(() => {
  if (props.task?.status === 'title_generated') return 'outline'
  if (props.task?.status === 'outline_generated') return 'content'
  return props.stage === 'titles' ? 'title' : props.stage
})
const retryLabel = computed(() => {
  if (props.busy) return t('workingAction')
  const points = quota.quota?.stage_costs?.[costStage.value]
  return Number.isInteger(points) ? t('retryCost', { points }, points) : t('retryPaid')
})
const stages = ['topic', 'titles', 'outline', 'content']
const position = computed(() => stages.indexOf(props.stage))
</script>
