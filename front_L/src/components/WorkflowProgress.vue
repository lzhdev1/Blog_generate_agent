<template>
  <section class="wf-panel wf-progress">
    <div class="wf-panel-head"><h2>{{ t('agentProgress') }}</h2><SvgIcon name="clock" :size="18" /></div>
    <ol class="wf-timeline">
      <li v-for="([key, , icon], index) in steps" :key="key"
        :class="{ 'is-active': index === active, 'is-done': index < active }"
        :aria-current="index === active ? 'step' : undefined">
        <span class="wf-node"><SvgIcon :name="index < active ? 'check' : icon" :size="18" /></span>
        <div class="wf-phase">
          <strong>{{ t(key) }}</strong>
          <small>{{ t(index === active ? 'working' : index < active ? 'done' : 'waiting') }}</small>
        </div>
      </li>
    </ol>
    <p class="wf-live" role="status"><span aria-hidden="true"></span>{{ progressText || t('waitingServer') }}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import SvgIcon from './SvgIcon.vue'
import { useWorkflowText } from '@/i18n/workflow'

const props = defineProps({
  type: { type: String, required: true },
  taskStatus: String, progressText: String, needImage: Boolean
})
const { t } = useWorkflowText()
const byStage = {
  titles: [
    ['titleResearch', ['researching_title'], 'search'],
    ['titleWriting', ['generating_titles'], 'title'],
    ['titleReview', ['reviewing_title'], 'review']
  ],
  outline: [
    ['outlineResearch', ['researching_outline'], 'search'],
    ['outlineWriting', ['generating_outline'], 'outline'],
    ['outlineReview', ['reviewing_outline'], 'review']
  ],
  content: [
    ['contentResearch', ['researching_content'], 'search'],
    ['writing', ['generating_content'], 'pen'],
    ['review', ['reviewing'], 'review'],
    ['images', ['generating_images'], 'image'],
    ['formatting', ['formatting'], 'format']
  ]
}
const steps = computed(() => byStage[props.type].filter(([key]) => key !== 'images' || props.needImage))
const active = computed(() => steps.value.findIndex(([, statuses]) => statuses.includes(props.taskStatus)))
</script>
