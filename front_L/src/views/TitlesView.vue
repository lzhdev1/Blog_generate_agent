<template>
  <WorkflowFrame stage="titles" :task="task" :busy="busy" :error="error" @reload="reload" @retry="regenerate" @replay="replay" @restore="restore">
    <section v-if="task?.status === 'pending' || !task?.titles?.length" class="wf-panel wf-ready">
      <h2>{{ t('choices') }}</h2>
      <p>{{ t(task?.status === 'pending' ? 'readyTitles' : 'titleEmpty') }}</p>
      <button class="wf-primary" :disabled="busy || quota.insufficient('title')" @click="regenerate">{{ t(busy ? 'workingAction' : 'startTitles') }}</button>
    </section>
    <form v-else class="wf-stack" @submit.prevent="submit">
      <section class="wf-panel">
        <div class="wf-panel-head">
          <h2 id="wf-choices">{{ t('choices') }} <span class="wf-count">{{ task.titles.length }}</span></h2>
          <button type="button" class="wf-text-btn" :disabled="busy || quota.insufficient('title')" @click="regenerate"><SvgIcon name="refresh" :size="14" />{{ t('regenerate') }}</button>
        </div>
        <div role="radiogroup" aria-labelledby="wf-choices" class="wf-choices">
          <label v-for="(candidate, index) in task.titles" :key="index" class="wf-choice" :class="{ 'is-selected': form.index === index }">
            <input type="radio" name="candidate" :checked="form.index === index" :disabled="busy" @change="select(index)" />
            <span class="wf-choice-number">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="wf-choice-text">{{ candidate }}</span>
            <span class="wf-radio" aria-hidden="true"></span>
          </label>
        </div>
        <label class="wf-field wf-title-field">
          <span>{{ t('useTitle') }}</span>
          <input v-model="form.title" required maxlength="512" :disabled="busy" />
          <small>{{ t('titleHint') }}</small>
        </label>
      </section>
      <section class="wf-panel">
        <div class="wf-panel-head"><h2>{{ t('settings') }}</h2></div>
        <div class="wf-form-grid">
          <label class="wf-field wf-full"><span>{{ t('purpose') }} <em>{{ t('optional') }}</em></span>
            <input v-model="form.purpose" maxlength="512" :disabled="busy" :placeholder="t('purposeHint')" />
          </label>
          <label class="wf-field"><span>{{ t('style') }}</span>
            <select v-model="form.style" :disabled="busy">
              <option value="">{{ t('auto') }}</option>
              <option v-for="style in styles" :key="style" :value="style">{{ t(style) }}</option>
            </select>
          </label>
          <label class="wf-checkbox"><input type="checkbox" v-model="form.needImage" :disabled="busy" /><span>{{ t('includeImages') }}</span></label>
          <label v-if="form.style === 'custom'" class="wf-field wf-full"><span>{{ t('customStyle') }}</span>
            <input v-model="form.customStyle" required maxlength="200" :disabled="busy" />
          </label>
          <label class="wf-field wf-full"><span>{{ t('outlineReq') }} <em>{{ t('optional') }}</em></span>
            <textarea v-model="form.brief" rows="3" maxlength="1000" :disabled="busy" :placeholder="t('outlinePlaceholder')"></textarea>
          </label>
        </div>
        <p v-if="validation" class="wf-validation" role="alert">{{ t(validation) }}</p>
        <div class="wf-actions"><button class="wf-primary" :disabled="busy || quota.insufficient('outline')">{{ t(busy ? 'workingAction' : 'nextOutline') }} <span aria-hidden="true">→</span></button></div>
      </section>
    </form>
    <template #failed-draft>
      <details v-if="task?.status === 'failed' && task.titles?.length" class="wf-panel wf-details" open>
        <summary>{{ t('failedTitles') }}</summary>
        <ol><li v-for="(title, index) in task.titles" :key="index">{{ title }}</li></ol>
      </details>
    </template>
    <template #aside>
      <section v-if="task?.status === 'title_generated' && score" class="wf-panel wf-assessment">
        <div class="wf-panel-head"><h2>{{ t('score') }}</h2><SvgIcon name="review" :size="17" /></div>
        <div v-if="score.total != null" class="wf-total">{{ score.total }}<small> / 10</small></div>
        <p class="wf-score-note">{{ t('scoreHelp') }}</p>
        <div v-for="metric in metrics" :key="metric" class="wf-metric">
          <template v-if="score[metric] != null">
            <span>{{ t(metric) }}</span><meter min="0" max="10" :value="score[metric]" :aria-label="t(metric)"></meter><b>{{ score[metric] }}</b>
          </template>
        </div>
        <div v-for="key in ['pros', 'cons']" :key="key">
          <template v-if="score[key]?.length"><h3>{{ t(key) }}</h3><ul><li v-for="point in score[key]" :key="point">{{ point }}</li></ul></template>
        </div>
      </section>
      <details v-if="research" class="wf-panel wf-details"><summary>{{ t('research') }}</summary><MarkdownRender :content="research" /></details>
    </template>
  </WorkflowFrame>
</template>

<script setup>
import { computed, ref } from 'vue'
import WorkflowFrame from '@/components/WorkflowFrame.vue'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
import { generateTitles, submitTitleConfig } from '@/api/task'
import { useQuotaStore } from '@/stores/quota'
import { useWorkflowText } from '@/i18n/workflow'
import { researchSummary } from '@/utils/taskWorkflow'
import { useTaskWorkspace, useTaskDraft } from '@/utils/useTaskWorkspace'

const { t } = useWorkflowText()
const quota = useQuotaStore()
const { task, error, busy, reload, run, replay, restore } = useTaskWorkspace()
const { form, clearDraft, keepSettings } = useTaskDraft(task, 'titles',
  data => data.status === 'title_generated' && JSON.stringify(data.titles),
  data => ({
    index: Math.max(0, data.titles.indexOf(data.selected_title)), title: data.selected_title || data.titles[0] || '',
    needImage: !!data.need_image, style: data.article_style || '', customStyle: data.article_style_custom || '',
    brief: data.extra_requirements || '', purpose: data.purpose || ''
  })
)
const validation = ref('')
const styles = ['popular_science', 'technical', 'essay', 'prose', 'note', 'custom']
const metrics = ['accuracy', 'uniqueness', 'seo']
const research = computed(() => researchSummary(task.value?.title_research))
const score = computed(() => {
  const index = form.value.index
  const scores = task.value?.title_scores || []
  const candidate = task.value?.titles?.[index]
  return scores.find(item => item.title === candidate) || (!scores[index]?.title && scores[index])
})

function select(index) {
  form.value.index = index
  form.value.title = task.value.titles[index]
  validation.value = ''
}
function regenerate() {
  if (task.value.status === 'title_generated' && form.value.title !== task.value.titles[form.value.index] && !window.confirm(t('replaceTitles'))) return
  validation.value = ''
  return run(async () => {
    if (task.value.status === 'title_generated') keepSettings(['style', 'customStyle', 'needImage', 'brief', 'purpose'])
    await generateTitles(task.value)
  })
}
function submit() {
  const data = form.value
  validation.value = !data.title.trim() ? 'invalidTitle' : data.style === 'custom' && !data.customStyle.trim() ? 'invalidStyle' : ''
  if (validation.value) return
  return run(async id => {
    await submitTitleConfig(task.value, {
      title: data.title.trim(), need_image: data.needImage, article_style: data.style || null,
      purpose: data.purpose?.trim() || null,
      article_style_custom: data.style === 'custom' ? data.customStyle.trim() : null,
      extra_requirements: data.brief.trim() || null
    })
    clearDraft(id)
  })
}
</script>
