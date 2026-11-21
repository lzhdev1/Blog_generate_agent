<template>
  <WorkflowFrame stage="content" :task="task" :busy="busy" :error="error" @reload="reload" @retry="start" @replay="replay" @restore="restore">
    <section v-if="task?.status === 'outline_generated' && task.outline_confirmed" class="wf-panel wf-ready">
      <h2>{{ t('startContent') }}</h2>
      <p>{{ t('readyContent') }}</p>
      <button class="wf-primary" :disabled="busy || quota.insufficient('content')" @click="start">{{ t(busy ? 'workingAction' : 'startContent') }} <span aria-hidden="true">→</span></button>
    </section>
    <template #recovery-actions>
      <router-link v-if="task?.content && (!task.job || task.job.stage === 'content')" class="wf-secondary" :to="'/task/' + task.id + '/revision'">{{ t('revisionAction') }}</router-link>
      <button v-if="task?.outline_confirmed && task.outline && !task.is_public" type="button" class="wf-secondary" :disabled="busy" @click="run(reopenOutline)">{{ t('adjustBrief') }}</button>
    </template>
    <template #failed-draft>
      <details v-if="task?.review_result" class="wf-panel wf-details" open>
        <summary>{{ t('previousReview') }}</summary>
        <ul v-if="task.review_result.review_opinions?.length">
          <li v-for="(op,index) in task.review_result.review_opinions" :key="index"><strong>{{ op.where }}</strong> {{ op.why }} {{ op.expected }}</li>
        </ul>
        <MarkdownRender v-if="task.review_result.feedback" :content="task.review_result.feedback" />
        <MarkdownRender v-if="task.review_result.opinions_text" :content="task.review_result.opinions_text" />
        <p v-if="!task.review_result.review_opinions?.length && !task.review_result.feedback && !task.review_result.opinions_text">{{ task.error || task.progress }}</p>
      </details>
      <details v-if="task?.content" class="wf-panel wf-details"><summary>{{ t('previousDraft') }}</summary><MarkdownRender :content="task.content" /></details>
    </template>
    <template #aside>
      <EvidenceSources v-if="task?.status === 'failed'" :sources="task.evidence_sources" />
      <details v-if="task?.status === 'failed' && task.content_research" class="wf-panel wf-details">
        <summary>{{ t('research') }}</summary><MarkdownRender :content="researchSummary(task.content_research)" />
      </details>
      <details v-if="task?.outline" class="wf-panel wf-details">
        <summary>{{ t('contentOutline') }}</summary>
        <MarkdownRender :content="task.outline" :highlight-image-markers="true" />
      </details>
    </template>
  </WorkflowFrame>
</template>

<script setup>
import WorkflowFrame from '@/components/WorkflowFrame.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
import EvidenceSources from '@/components/EvidenceSources.vue'
import { generateContent, reopenOutline } from '@/api/task'
import { useQuotaStore } from '@/stores/quota'
import { useWorkflowText } from '@/i18n/workflow'
import { useTaskWorkspace } from '@/utils/useTaskWorkspace'
import { researchSummary } from '@/utils/taskWorkflow'

const { t } = useWorkflowText()
const quota = useQuotaStore()
const { task, error, busy, reload, run, replay, restore } = useTaskWorkspace()
const start = () => run(() => generateContent(task.value))
</script>
