<template>
  <section v-if="entries.length" class="source-panel">
    <h3>{{ t('sources') }}</h3>
    <p v-if="editable" class="cite-hint">{{ t('citationHint', { id:entries[0].id }) }}</p>
    <ul>
      <li v-for="source in entries" :key="source.id">
        <span class="source-id">[{{ source.id }}]</span>
        <div><a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title || source.url }}</a>
          <small>{{ [source.site, source.published].filter(Boolean).join(' · ') }}</small>
          <details v-if="source.excerpt"><summary>{{ t('sourceExcerpt') }}</summary><p>{{ source.excerpt }}</p></details>
        </div>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useWorkflowText } from '@/i18n/workflow'
import { evidenceSources } from '@/utils/evidenceSources'
const props = defineProps({ sources: Array, editable: Boolean })
const { t } = useWorkflowText()
const entries = computed(() => evidenceSources(props.sources))
</script>

<style scoped>
.source-panel{border:1px solid var(--line);border-radius:8px;background:var(--surface);padding:18px 22px;overflow-wrap:anywhere}
.source-panel h3{font:650 18px/1.5 var(--serif);margin:0 0 8px}.source-panel ul{list-style:none;padding:0;margin:0}
.cite-hint{font-size:13px;color:var(--muted);margin:4px 0 9px}
.source-panel li{display:flex;align-items:baseline;gap:9px;padding:8px 0}.source-panel li+li{border-top:1px solid var(--line)}
.source-id{font:12px var(--mono);color:var(--muted)}.source-panel a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}
.source-panel small,.source-panel details{display:block;color:var(--muted);font-size:12px;margin-top:3px}.source-panel summary{cursor:pointer}.source-panel details p{margin:5px 0;line-height:1.65}
</style>
