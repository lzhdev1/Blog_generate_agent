<template>
  <div class="revision-page">
    <router-link class="reader-back" :to="backPath"><SvgIcon name="back" :size="15" />{{ t('back') }}</router-link>
    <header class="page-heading"><div><h1>{{ t('heading') }}</h1><p>{{ task?.selected_title || task?.topic }}</p></div></header>
    <p v-if="loading" class="empty-panel" role="status">{{ t('loading') }}</p>
    <div v-else-if="!task" class="empty-panel" role="alert">{{ error }} <button class="quiet-action" @click="load">{{ t('reload') }}</button></div>
    <template v-else>
      <div v-if="error || stale || conflict" class="revision-notice" role="alert">
        <p>{{ stale ? t('stale') : conflict ? t('conflict') : error }}</p>
        <button v-if="conflict || error" type="button" class="quiet-action" :disabled="busy" @click="reloadFromServer">{{ t('reload') }}</button>
      </div>
      <div class="revision-layout">
        <section class="revision-editor">
          <div class="editor-head"><h2>{{ t('manuscript') }}</h2><span role="status">{{ dirty ? t('unsaved') : draft ? t('saved', {version:draft.version}) : t('original') }}</span></div>
          <div class="editor-tabs" role="group" :aria-label="t('manuscript')"><button v-for="key in ['edit','preview']" :key="key" type="button" :aria-pressed="tab === key" @click="tab=key">{{ t(key) }}</button></div>
          <label v-if="tab === 'edit'" class="editor-label"><span>{{ t('markdown') }}</span><textarea v-model="content" rows="17" maxlength="64000" :readonly="locked || stale || conflict || busy" /></label>
          <div v-else class="preview"><MarkdownRender :content="content" :evidence="sources" /></div>
          <label class="query-label"><span>{{ t('query') }}</span>
            <input v-model="sourceQuery" maxlength="300" :placeholder="t('queryHint')" :readonly="locked || stale || conflict || busy" />
          </label>
          <div class="revision-actions">
            <button class="quiet-action" :disabled="busy || locked || stale || conflict || !canSave" @click="save">{{ t('save') }}</button>
            <button v-if="canReview" class="primary-action" :disabled="busy || conflict || stale || (!pendingKey && quota.insufficient('revision'))" @click="review">{{ pendingKey ? t('replay') : t('review', {cost}) }}</button>
            <button v-if="draft?.status === 'approved' && !dirty" class="primary-action" :disabled="busy || conflict || stale" @click="apply">{{ t('apply') }}</button>
          </div>
        </section>
        <aside class="revision-aside">
          <section class="revision-panel">
            <h2>{{ t('reviewStatus') }}</h2>
            <strong class="verdict">{{ t('states.' + (draft?.status || 'new')) }}</strong>
            <p v-if="reconnecting" role="status">{{ t('reconnecting') }}</p>
            <p>{{ t('privateInfo') }}</p>
            <p v-if="draft?.status === 'approved'">{{ t('applyHint') }}</p>
            <p v-if="draft?.error" role="alert">{{ draft.error }}</p>
            <button v-if="draft" class="link-action" :disabled="busy || locked" @click="discard">{{ t('discard') }}</button>
          </section>
          <ReviewFindings v-if="findings" :report="findings" :heading="t('findings')" />
          <EvidenceSources :sources="sources" editable />
          <GenerationAllowance class="revision-panel" stage="revision" />
        </aside>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import MarkdownRender from '@/components/MarkdownRender.vue'
import ReviewFindings from '@/components/ReviewFindings.vue'
import EvidenceSources from '@/components/EvidenceSources.vue'
import GenerationAllowance from '@/components/GenerationAllowance.vue'
import SvgIcon from '@/components/SvgIcon.vue'
import { getTask, getRevision, saveRevision, reviewRevision, applyRevision, discardRevision } from '@/api/task'
import { useQuotaStore } from '@/stores/quota'
import { useAuthStore } from '@/stores/auth'
import { admissionWasRejected } from '@/utils/generationJournal'
import { taskPath } from '@/utils/taskWorkflow'

import messages from '@/i18n/revision'

const { t } = useI18n({ useScope:'local', messages })
const route=useRoute(), router=useRouter(), auth=useAuthStore(), quota=useQuotaStore()
const id=route.params.id
const task=ref(null), draft=ref(null), content=ref(''), sourceQuery=ref(''), tab=ref('edit')
const loading=ref(true),busy=ref(false),conflict=ref(false),error=ref(''),pendingKey=ref('')
const reconnecting=ref(false)
const original=computed(()=>task.value?.formatted_content || task.value?.content || '')
const savedContent=computed(()=>draft.value?.content ?? original.value)
const dirty=computed(()=>content.value !== savedContent.value || sourceQuery.value.trim() !== (draft.value?.source_query || ''))
const sources=computed(()=>draft.value?.evidence_sources?.length ? draft.value.evidence_sources : task.value?.evidence_sources)
const locked=computed(()=>['queued','reviewing'].includes(draft.value?.status))
const stale=computed(()=>!!draft.value && draft.value.base_revision !== task.value?.revision)
const canSave=computed(()=>content.value.trim() && (dirty.value || !draft.value))
const canReview=computed(()=>draft.value && !dirty.value && (pendingKey.value || ['draft','failed'].includes(draft.value.status)))
const cost=computed(()=>quota.quota?.stage_costs?.revision ?? 1)
const backPath=computed(()=>task.value ? taskPath(task.value) : '/my-articles')
const findings=computed(()=>{
  const result=draft.value?.review_result || (!draft.value && task.value?.review_result)
  return result && !result.passed && (result.review_opinions?.length || result.feedback || result.opinions_text) ? result : null
})
let timer, active=true, loadEpoch=0, pollFailures=0, pollingEpoch=null
function receiptKey() { return `blog-agent-review:${auth.user?.id}:${id}:${draft.value?.version}` }
function setReceipt(value) {
  pendingKey.value=value
  try { if (value) sessionStorage.setItem(receiptKey(),value); else sessionStorage.removeItem(receiptKey()) } catch { /* Retain the key in memory. */ }
}
function showError(err) {
  const detail=err.response?.data?.detail
  error.value=typeof detail === 'string' ? detail : detail?.message || err.message || t('error')
  if (err.response?.status === 409) conflict.value=true
}
function pollWhenActive(delay=2500) {
  clearTimeout(timer)
  if (!active || !locked.value || pollingEpoch === loadEpoch) return
  timer=setTimeout(async ()=>{
    const epoch=loadEpoch
    pollingEpoch=epoch
    let nextDelay=2500
    try {
      const current=await getRevision(id,true)
      if (!active || epoch !== loadEpoch) return
      if (!current || current.version !== draft.value?.version) { conflict.value=true; return }
      draft.value=current
      reconnecting.value=false
      pollFailures=0
      if (!locked.value) void quota.refresh(true)
    } catch (err) {
      if (!active || epoch !== loadEpoch) return
      const status=err.response?.status
      if (status === 401 || status === 403 || status === 404) {
        task.value=null; draft.value=null; content.value=''; sourceQuery.value=''
        showError(err)
        return
      }
      if (status && status < 500 && status !== 408 && status !== 429) { showError(err); return }
      reconnecting.value=true
      nextDelay=Math.min(30000, 2500 * 2 ** Math.min(++pollFailures,4))
    } finally {
      if (pollingEpoch === epoch) pollingEpoch=null
    }
    pollWhenActive(nextDelay)
  },delay)
}
function reconnect() {
  if (locked.value && !conflict.value && !error.value && !document.hidden) pollWhenActive(0)
}
async function load() {
  const epoch=++loadEpoch
  clearTimeout(timer)
  loading.value=true; error.value=''; conflict.value=false; task.value=null; draft.value=null; content.value=''; sourceQuery.value=''
  reconnecting.value=false; pollFailures=0
  try {
    const [data,current]=await Promise.all([getTask(id),getRevision(id)])
    if (!active || epoch !== loadEpoch) return
    task.value=data; draft.value=current; content.value=savedContent.value; sourceQuery.value=current?.source_query || ''
    pendingKey.value=''
    try { if (current) pendingKey.value=sessionStorage.getItem(receiptKey()) || '' } catch { /* Storage is optional. */ }
    pollWhenActive()
  } catch (err) { if (active && epoch === loadEpoch) showError(err) }
  finally { if (active && epoch === loadEpoch) loading.value=false }
}
function reloadFromServer() {
  if (!dirty.value || window.confirm(t('reloadAsk'))) void load()
}
async function perform(action) {
  if (busy.value) return
  busy.value=true; error.value=''
  const owner=auth.user?.id
  const current=()=>active && owner === auth.user?.id
  try { await action(current) }
  catch (err) { if (current()) showError(err) }
  finally { if (active) busy.value=false }
}
function save() {
  return perform(async isCurrent=>{
    const current=await saveRevision(id,{content:content.value,source_query:sourceQuery.value.trim() || null,expected_revision:task.value.revision,expected_version:draft.value?.version ?? 0})
    if (!isCurrent()) return
    setReceipt('')
    draft.value=current; content.value=current.content; sourceQuery.value=current.source_query || ''
  })
}
function review() {
  return perform(async isCurrent=>{
    if (!pendingKey.value) setReceipt(Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''))
    try {
      const current=await reviewRevision(id,draft.value.version,pendingKey.value)
      if (!isCurrent()) return
      setReceipt(''); draft.value=current; void quota.refresh(true); pollWhenActive()
    } catch (err) {
      if (isCurrent() && admissionWasRejected(err)) setReceipt('')
      throw err
    }
  })
}
function apply() {
  if (!window.confirm(t('applyAsk'))) return
  return perform(async isCurrent=>{
    const result=await applyRevision(id,{expected_version:draft.value.version,expected_revision:task.value.revision})
    if (!isCurrent()) return
    ElMessage.success(t('applied')); await router.replace(taskPath(result))
  })
}
function discard() {
  if (!window.confirm(t('discardAsk'))) return
  return perform(async isCurrent=>{
    await discardRevision(id,draft.value.version)
    if (isCurrent()) { setReceipt(''); await load() }
  })
}
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue='' } }
onBeforeRouteLeave(()=>!dirty.value || window.confirm(t('leave')))
watch(()=>auth.user?.id,()=>{ void load() })
onMounted(()=>{
  void load()
  window.addEventListener('beforeunload',beforeUnload)
  window.addEventListener('online',reconnect)
  document.addEventListener('visibilitychange',reconnect)
})
onBeforeUnmount(()=>{
  active=false; clearTimeout(timer)
  window.removeEventListener('beforeunload',beforeUnload)
  window.removeEventListener('online',reconnect)
  document.removeEventListener('visibilitychange',reconnect)
})
</script>

<style scoped>
.query-label{display:grid;gap:5px;margin:12px 0;color:var(--muted);font-size:13px}.query-label input{width:100%;padding:8px 10px;color:var(--ink);border:1px solid var(--line);border-radius:4px;background:var(--surface)}
.revision-page{max-width:1160px;margin:auto}.reader-back{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);margin-bottom:16px}
.revision-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(235px,31%);align-items:start;gap:16px}.revision-editor,.revision-panel{padding:20px;background:var(--surface);border:1px solid var(--line);border-radius:8px;min-width:0}.revision-aside{display:grid;gap:12px;min-width:0}
.revision-page h2{font:650 19px/1.5 var(--serif);margin:0}.revision-panel p,.editor-label span,.editor-head span{font-size:13px;color:var(--muted)}.revision-panel p{margin:8px 0}.verdict{display:block;margin-top:7px;color:var(--accent)}
.editor-head,.editor-tabs,.revision-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.editor-head{justify-content:space-between}.editor-tabs{margin:10px 0}.editor-tabs button{border:0;border-bottom:2px solid transparent;background:none;padding:5px 10px;color:var(--muted)}.editor-tabs [aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
.editor-label{display:grid;gap:5px}.editor-label textarea{display:block;width:100%;min-height:270px;padding:12px;resize:vertical;line-height:1.7;font-family:var(--mono);font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:5px}.preview{min-height:270px;overflow-wrap:anywhere}.revision-actions{margin-top:13px}.revision-notice{margin-bottom:14px;padding:12px 16px;background:var(--tint);border-radius:6px}.revision-notice p{margin:0 0 7px}
@media(max-width:760px){.revision-layout{grid-template-columns:1fr}.revision-panel,.revision-editor{padding:15px}}
</style>
