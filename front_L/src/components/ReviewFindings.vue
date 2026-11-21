<template>
  <section v-if="report" class="review-findings">
    <h3>{{ heading || t('handoffIssues') }}</h3>
    <ol v-if="report.review_opinions?.length">
      <li v-for="(item, index) in report.review_opinions" :key="index">
        <strong>{{ item.where || item.point }}</strong>
        <p v-if="item.why">{{ item.why }}</p>
        <p v-if="item.expected"><b>{{ t('changeRequested') }}</b> {{ item.expected }}</p>
      </li>
    </ol>
    <MarkdownRender v-if="report.feedback || report.opinions_text" :content="report.feedback || report.opinions_text" />
  </section>
</template>

<script setup>
import MarkdownRender from './MarkdownRender.vue'
import { useWorkflowText } from '@/i18n/workflow'
defineProps({ report: Object, heading: String })
const { t } = useWorkflowText()
</script>

<style scoped>
.review-findings{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--warning);padding:15px 18px;border-radius:6px;overflow-wrap:anywhere}
.review-findings h3{font:650 17px/1.5 var(--serif);margin:0}.review-findings ol{margin:8px 0 0;padding-left:1.5em}.review-findings li+li{margin-top:10px}.review-findings p{font-size:14px;margin:4px 0}.review-findings b{font-weight:600}
</style>
