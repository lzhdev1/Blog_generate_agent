<template>
  <div class="snapshot">
    <router-link class="back" :to="{path:'/my-articles',query:{tab:route.params.kind}}"><SvgIcon name="back" :size="16" />{{ t('studio.returnLibrary') }}</router-link>
    <div v-if="busy" class="empty-panel">{{ t('studio.loading') }}</div>
    <div v-else-if="!data" class="empty-panel"><p>{{ t('studio.listError') }}</p><button class="quiet-action" @click="load">{{ t('studio.retry') }}</button></div>
    <article v-else>
      <header><small>{{ t(route.params.kind === 'purchased' ? 'studio.purchaseHistory' : 'studio.downloadHistory') }} · {{ articleDate(data.created_at,locale) }}</small>
        <h1>{{ data.title }}</h1>
        <button class="quiet-action" @click="exportMarkdown(data.title,data.content)"><SvgIcon name="download" :size="15" />{{ t('studio.export') }}</button>
      </header>
      <MarkdownRender :content="body" />
    </article>
  </div>
</template>
<script setup>
import {ref, computed, onMounted} from 'vue'
import {useRoute} from 'vue-router'
import {useI18n} from 'vue-i18n'
import {getSnapshot} from '@/api/article'
import {articleDate,exportMarkdown,withoutDuplicateTitle} from '@/utils/articles'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
const route=useRoute(), {t,locale}=useI18n()
const busy=ref(true), data=ref(null)
const body=computed(()=>withoutDuplicateTitle(data.value?.content,data.value?.title))
async function load() {
  busy.value=true
  try {data.value=await getSnapshot(route.params.kind,route.params.recordId)} catch {data.value=null}
  finally {busy.value=false}
}
onMounted(load)
</script>
<style scoped>
.snapshot{max-width:860px;margin:auto}.back{display:inline-flex;gap:8px;align-items:center;margin-bottom:18px;color:var(--muted);font-size:13px}
article{background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:clamp(20px,4vw,56px)}header{padding-bottom:22px;border-bottom:1px solid var(--line)}h1{font:700 clamp(27px,3vw,40px)/1.4 var(--serif);margin:9px 0 15px}header small{color:var(--muted)}
</style>
