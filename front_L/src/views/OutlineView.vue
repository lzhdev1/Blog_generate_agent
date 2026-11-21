<template>
  <WorkflowFrame stage="outline" :task="task" :busy="busy" :error="error" @reload="reload" @retry="regenerate" @replay="replay" @restore="restore">
    <form class="wf-stack" @submit.prevent="submit">
      <section class="wf-panel wf-manuscript">
        <div class="wf-panel-head">
          <h2>{{ t('outlineDoc') }}</h2>
          <button type="button" class="wf-text-btn" :disabled="busy || quota.insufficient('outline')" @click="regenerate"><SvgIcon name="refresh" :size="14" />{{ t('regenerate') }}</button>
        </div>
        <div class="wf-editor-tools" role="group" :aria-label="t('outlineDoc')">
          <button type="button" :aria-pressed="!editing" @click="editing = false"><SvgIcon name="document" :size="14" />{{ t('preview') }}</button>
          <button type="button" :aria-pressed="editing" @click="editing = true"><SvgIcon name="edit" :size="14" />{{ t('edit') }}</button>
        </div>
        <label v-if="editing" class="wf-field">
          <span>{{ t('editOutline') }}</span>
          <textarea v-model="form.outline" class="wf-editor" rows="15" :disabled="busy"></textarea>
        </label>
        <div v-else class="wf-manuscript-body"><MarkdownRender :content="form.outline || ''" :highlight-image-markers="true" /></div>
      </section>
      <section class="wf-panel">
        <div class="wf-panel-head"><h2>{{ t('writingSettings') }}</h2></div>
        <div class="wf-form-grid">
          <label class="wf-field"><span>{{ t('target') }}</span>
            <input v-model.number="form.wordCount" type="number" min="100" max="10000" step="1" required :disabled="busy" />
            <small>{{ t('targetHint') }}</small>
          </label>
          <label class="wf-field"><span>{{ t('audience') }}</span>
            <select v-model="form.level" :disabled="busy"><option v-for="level in levels" :key="level" :value="level">{{ t(level) }}</option></select>
          </label>
          <label v-if="task?.need_image" class="wf-field wf-full"><span>{{ t('imageSource') }}</span>
            <select v-model="form.imageSource" :disabled="busy"><option value="api">{{ t('api') }}</option><option value="ai">{{ t('ai') }}</option></select>
          </label>
          <label class="wf-field wf-full"><span>{{ t('bodyReq') }} <em>{{ t('optional') }}</em></span>
            <textarea v-model="form.brief" rows="3" maxlength="1000" :disabled="busy" :placeholder="t('bodyPlaceholder')"></textarea>
          </label>
        </div>
        <p v-if="validation" class="wf-validation" role="alert">{{ t(validation) }}</p>
        <div class="wf-actions"><button class="wf-primary" :disabled="busy || quota.insufficient('content')">{{ t(busy ? 'workingAction' : 'nextContent') }} <span aria-hidden="true">→</span></button></div>
      </section>
    </form>
    <template #failed-draft>
      <details v-if="task?.status === 'failed' && task.outline" class="wf-panel wf-details" open>
        <summary>{{ t('failedOutline') }}</summary>
        <MarkdownRender :content="task.outline" :highlight-image-markers="true" />
      </details>
    </template>
    <template #aside>
      <details v-if="research" class="wf-panel wf-details"><summary>{{ t('research') }}</summary><MarkdownRender :content="research" /></details>
    </template>
  </WorkflowFrame>
</template>

<script setup>
import { computed, ref } from 'vue'
import WorkflowFrame from '@/components/WorkflowFrame.vue'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
import { confirmOutline, regenerateOutline, generateContent } from '@/api/task'
import { useQuotaStore } from '@/stores/quota'
import { useWorkflowText } from '@/i18n/workflow'
import { researchSummary } from '@/utils/taskWorkflow'
import { useTaskWorkspace, useTaskDraft } from '@/utils/useTaskWorkspace'

const { t } = useWorkflowText()
const quota = useQuotaStore()
const { task, error, busy, reload, run, replay, restore } = useTaskWorkspace()
const { form, clearDraft, keepSettings } = useTaskDraft(task, 'outline',
  data => data.status === 'outline_generated' && data.outline,
  data => ({
    outline: data.outline, wordCount: data.word_count || 800, level: data.level || 'medium',
    brief: data.content_extra_requirements || '', imageSource: data.image_source || 'api'
  })
)
const editing = ref(false)
const validation = ref('')
const levels = ['general', 'medium', 'advanced', 'professional']
const research = computed(() => researchSummary(task.value?.outline_research))

function regenerate() {
  if (task.value.status === 'outline_generated' && form.value.outline !== task.value.outline && !window.confirm(t('replaceOutline'))) return
  return run(async () => {
    if (task.value.status === 'outline_generated') keepSettings(['wordCount', 'level', 'brief', 'imageSource'])
    await regenerateOutline(task.value)
    editing.value = false
    validation.value = ''
  })
}
function submit() {
  const data = form.value
  validation.value = ''
  if (!data.outline?.trim()) {
    validation.value = 'invalidOutline'
    editing.value = true
    return
  }
  if (!Number.isInteger(data.wordCount) || data.wordCount < 100 || data.wordCount > 10000) {
    validation.value = 'invalidWords'
    return
  }
  return run(async id => {
    const confirmed = await confirmOutline(id, {
      outline: data.outline.trim(), word_count: data.wordCount, level: data.level,
      content_extra_requirements: data.brief.trim() || null,
      image_source: task.value.need_image ? data.imageSource : null
    })
    clearDraft(id)
    await generateContent(confirmed)
  })
}
</script>
