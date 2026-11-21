<template>
  <div class="reader">
    <router-link class="reader-back" :to="article?.is_owner ? '/my-articles' : '/articles'"><SvgIcon name="back" :size="16" />{{ t(article?.is_owner ? 'studio.library' : 'studio.explore') }}</router-link>
    <div v-if="loading" class="empty-panel" role="status">{{ t('studio.loading') }}</div>
    <div v-else-if="!article" class="empty-panel"><h2>{{ missing ? r('unavailable') : t('studio.listError') }}</h2><button class="quiet-action" @click="load">{{ t('studio.retry') }}</button></div>
    <template v-else>
      <header class="reader-head">
        <div class="byline"><span>{{ article.is_demo ? t('studio.demo') : styleName || t('studio.article') }}</span><i>·</i>{{ article.nickname || t('studio.by') }}<i>·</i>{{ articleDate(article.created_at,locale) }}</div>
        <h1>{{ article.title }}</h1>
        <div class="reader-actions">
          <template v-if="article.is_owner">
            <button class="quiet-action" @click="copy"><SvgIcon name="copy" :size="15" />{{ t('studio.copy') }}</button>
            <button class="quiet-action" @click="act('download')"><SvgIcon name="download" :size="15" />{{ r('download') }}</button>
            <router-link v-if="editionMatches" class="quiet-action" :to="'/task/' + id + '/revision'"><SvgIcon name="edit" :size="15" />{{ r('revisionAction') }}</router-link>
            <button v-if="editionMatches" class="primary-action" :disabled="busy" @click="openPublishing">{{ r('share') }} · {{ t(notes.is_public ? 'studio.public' : 'studio.private') }}</button>
          </template>
          <template v-else>
            <button class="quiet-action" :aria-pressed="article.liked" :disabled="busy" @click="act('like')"><SvgIcon name="like" :size="15" />{{ t(article.liked ? 'studio.liked' : 'studio.like') }} {{ article.like_count }}</button>
            <button class="quiet-action" :aria-pressed="article.favorited" :disabled="busy" @click="act('favorite')"><SvgIcon name="star" :size="15" />{{ t(article.favorited ? 'studio.saved' : 'studio.favorite') }}</button>
            <button v-if="article.allow_download || article.is_demo" class="primary-action" :disabled="busy" @click="act(needsPurchase ? 'purchase' : 'download')"><SvgIcon name="download" :size="15" />{{ needsPurchase ? r('buy') + ' · ¥' + article.download_price : r('download') }}</button>
          </template>
        </div>
      </header>
      <p v-if="conflictMessage || (notes && !editionMatches)" class="reader-conflict" role="alert">{{ conflictMessage || r('notesChanged') }}
        <router-link v-if="reviewRequired" class="link-action" :to="'/task/' + id + '/revision'">{{ r('submitRevision') }}</router-link>
        <button v-else class="link-action" :disabled="busy" @click="load">{{ t('studio.retry') }}</button>
      </p>
      <nav v-if="article.is_owner" class="reader-tabs" :aria-label="t('studio.reading')">
        <button v-for="item in ['body','notes']" :key="item" :aria-pressed="tab === item" @click="tab=item">{{ r(item) }}</button>
      </nav>
      <template v-if="tab === 'body'"><article class="reader-sheet"><MarkdownRender :content="body" :evidence="article.evidence_sources" /></article><EvidenceSources class="reader-sources" :sources="article.evidence_sources" /></template>
      <div v-else-if="editionMatches" class="notes">
        <div v-if="notes.progress" class="generation-note"><SvgIcon name="review" :size="16" /><span>{{ notes.progress }}</span></div>
        <section v-if="notes.review_result" class="note-panel">
          <div class="note-head"><h2>{{ r('review') }}</h2><span class="score"><template v-if="review.score != null">{{ review.score }} / 100 · </template>{{ r(review.skipped ? 'skipped' : review.passed ? 'pass' : 'fail') }}</span></div>
          <div v-if="review.dimension_scores" class="metrics"><div v-for="dim in dimensions.filter(key => review.dimension_scores[key] != null)" :key="dim"><span>{{ r(dim) }}</span><meter min="0" max="100" :value="review.dimension_scores[dim]"></meter><b>{{ review.dimension_scores[dim] }}</b></div></div>
          <ul v-if="review.pass_reasons?.length"><li v-for="(reason,i) in review.pass_reasons" :key="i">{{ reason }}</li></ul>
          <div v-for="(op,i) in review.review_opinions || []" :key="i" class="opinion"><strong>{{ op.where }}</strong><p>{{ op.why }}</p><p>{{ op.expected }}</p></div>
          <MarkdownRender v-if="review.feedback" :content="review.feedback" />
          <small v-if="review.traffic_forecast || review.heat_level">{{ r('forecast') }} · {{ review.traffic_forecast || review.heat_level }}</small>
        </section>
        <details class="note-panel" open><summary>{{ r('brief') }}</summary><dl>
          <template v-for="[key,value] in brief" :key="key"><dt>{{ r(key) }}</dt><dd>{{ value }}</dd></template>
        </dl></details>
        <details v-if="notes.outline" class="note-panel"><summary>{{ r('structure') }}</summary><MarkdownRender :content="notes.outline" :highlight-image-markers="true" /></details>
        <details v-if="notes.writing_thoughts" class="note-panel"><summary>{{ r('planning') }}</summary><MarkdownRender :content="notes.writing_thoughts" /></details>
        <EvidenceSources :sources="notes.evidence_sources" />
        <details v-for="key in researchKeys.filter(key => notes[key])" :key="key" class="note-panel"><summary>{{ r(key) }}</summary><MarkdownRender :content="researchSummary(notes[key])" /></details>
        <GenerationAllowance class="note-panel" stage="content" />
        <p v-if="quota.rejection && String(quota.rejection.taskId) === String(id)" class="generation-note" role="alert">{{ quota.rejection.message }}</p>
        <button class="quiet-action regen" :disabled="busy || (!pending && quota.insufficient('content'))" @click="act('regenerate')"><SvgIcon name="refresh" :size="15" />{{ r(pending ? 'checkRequest' : 'regenerate') }}</button>
      </div>
      <div v-else class="empty-panel"><p>{{ r('reportIssue') }}</p><button class="quiet-action" @click="load">{{ t('studio.retry') }}</button></div>
    </template>
    <el-dialog v-model="publishing" :title="r('share')" width="420px">
      <el-form label-position="top">
        <el-form-item :label="r('public')"><el-switch v-model="form.is_public" /></el-form-item>
        <el-form-item v-if="form.is_public" :label="r('allow')"><el-switch v-model="form.allow_download" /></el-form-item>
        <el-form-item v-if="form.is_public && form.allow_download" :label="r('price')"><el-input-number v-model="form.download_price" :min="0" :max="100000" :precision="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="publishing=false">{{ r('cancel') }}</el-button><el-button type="primary" :loading="busy" @click="savePublishing">{{ r('save') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, reactive, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownRender from '@/components/MarkdownRender.vue'
import EvidenceSources from '@/components/EvidenceSources.vue'
import GenerationAllowance from '@/components/GenerationAllowance.vue'
import { useQuotaStore } from '@/stores/quota'
import SvgIcon from '@/components/SvgIcon.vue'
import readerMessages from '@/i18n/reader'
import { getArticle, toggleLike, toggleFavorite, purchaseArticle, downloadArticle, updateVisibility } from '@/api/article'
import { getBlogDetail, generateContent, pendingGeneration } from '@/api/task'
import { articleDate, exportMarkdown, withoutDuplicateTitle } from '@/utils/articles'
import { researchSummary } from '@/utils/taskWorkflow'
import { useAuthStore } from '@/stores/auth'
const {t,te,locale}=useI18n({useScope:'global'})
const {t:r}=useI18n({useScope:'local',messages:readerMessages})
const route=useRoute(), router=useRouter(), auth=useAuthStore()
const quota=useQuotaStore()
const id=route.params.id
const pending=computed(()=>pendingGeneration(id))
const article=ref(null),notes=ref(null),tab=ref('body'),loading=ref(true),busy=ref(false),missing=ref(false)
const publishing=ref(false),form=reactive({is_public:false,allow_download:false,download_price:0})
const publishingRevision=ref(''),conflictMessage=ref(''),reviewRequired=ref(false)
const editionMatches=computed(()=>!!article.value?.revision && notes.value?.revision === article.value.revision)
const review=computed(()=>notes.value?.review_result || {})
const dimensions=['outline_compliance','research_usage','relevance','logic_flow','style_match']
const researchKeys=['title_research','outline_research','content_research']
const body=computed(()=>withoutDuplicateTitle(article.value?.content, article.value?.title))
const styleName=computed(()=>{
  const style=article.value?.article_style
  if(style === 'custom' && notes.value?.article_style_custom) return notes.value.article_style_custom
  return style && te('studio.style.'+style) ? t('studio.style.'+style) : ''
})
const needsPurchase=computed(()=>!article.value?.is_demo && article.value?.download_price > 0 && !article.value?.purchased)
const brief=computed(()=>{
  const n=notes.value || {}
  return [['topic',n.topic],['purpose',n.purpose],['length',n.target_word_count],['style',styleName.value],['audience',n.level && r(n.level)],['illustrations',n.need_image ? (n.image_source && r(n.image_source)) : r('noImages')],['outlineBrief',n.extra_requirements],['bodyBrief',n.content_extra_requirements]].filter(([,v])=>v)
})
let loadVersion = 0
async function load() {
  const version = ++loadVersion
  loading.value=true
  conflictMessage.value=''
  reviewRequired.value=false
  publishing.value=false
  notes.value=null
  missing.value=false
  try {
    const edition = await getArticle(id)
    if (version !== loadVersion) return
    article.value = edition
    if (edition.is_owner) {
      try {
        const detail = await getBlogDetail(id)
        if (version === loadVersion) notes.value = detail
      } catch { /* Keep the article readable if its editorial notes are unavailable. */ }
    }
  } catch(e) {
    if (version === loadVersion) { article.value=null; missing.value=e.response?.status === 404 }
  } finally { if (version === loadVersion) loading.value=false }
}
onMounted(load)
watch(()=>auth.user?.id,()=>{tab.value='body';load()})
function openPublishing() {
  if (!editionMatches.value) return
  publishingRevision.value=article.value.revision
  Object.assign(form,{is_public:!!notes.value.is_public,allow_download:!!notes.value.allow_download,download_price:Number(notes.value.download_price) || 0})
  publishing.value=true
}
async function handleConflict(error) {
  if (error.response?.status !== 409) return
  if (error.response.data?.detail?.code === 'review_required') {
    publishing.value=false
    reviewRequired.value=true
    conflictMessage.value=r('reviewRequired')
    return
  }
  await load()
  conflictMessage.value=r('versionConflict')
}
async function savePublishing() {
  if(busy.value)return
  busy.value=true
  try {
    const allow=form.is_public && form.allow_download
    const data=await updateVisibility(id,{expected_revision:publishingRevision.value,is_public:form.is_public,allow_download:allow,download_price:allow ? form.download_price || 0 : 0})
    const visibility = { revision:data.revision, is_public:data.is_public, allow_download:data.allow_download, download_price:data.download_price }
    Object.assign(notes.value,visibility)
    Object.assign(article.value,visibility)
    publishing.value=false
    ElMessage.success(r('saved'))
  } catch (error) { await handleConflict(error) }
  finally {busy.value=false}
}
async function copy() {
  try {await navigator.clipboard.writeText(article.value.content);ElMessage.success(r('copied'))}
  catch { ElMessage.warning(r('copyFail')) }
}
async function act(action) {
  if(busy.value)return
  if(!auth.isLoggedIn) {await router.push({path:'/login',query:{redirect:route.fullPath}});return}
  busy.value=true
  try {
    if(action === 'like') Object.assign(article.value,await toggleLike(id))
    if(action === 'favorite') Object.assign(article.value,await toggleFavorite(id))
    if(action === 'download') {const data=await downloadArticle(id);exportMarkdown(data.title,data.content)}
    if(action === 'purchase') {
      const offer={expected_revision:article.value.revision,expected_price:article.value.download_price}
      await ElMessageBox.confirm(r('buyConfirm',{price:offer.expected_price}),r('buy'),{confirmButtonText:r('confirm'),cancelButtonText:r('cancel')})
      await purchaseArticle(id,offer)
      article.value.purchased=true
      ElMessage.success(r('bought'))
      await auth.fetchMe()
    }
    if(action === 'regenerate') {
      if (!pending.value) {
        await ElMessageBox.confirm(r('replace'),r('regenerate'),{type:'warning',confirmButtonText:r('regenerate'),cancelButtonText:r('cancel')})
        try {await generateContent({id, status:'completed'})}
        catch(e) {if(!pendingGeneration(id) && e.response?.status !== 409) throw e}
      }
      await router.push('/task/'+id+'/generating')
    }
  } catch (error) { if (action === 'purchase') await handleConflict(error) }
  finally {busy.value=false}
}
</script>

<style scoped>
.reader-sources{max-width:860px;margin:12px auto}.reader-conflict{background:var(--tint);color:var(--ink);padding:12px 16px;border-radius:6px;margin:0 0 12px;font-size:14px}
.reader{max-width:940px;margin:auto}.reader-back{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--muted);margin-bottom:20px}.reader-head{border-top:2px solid var(--ink);padding:22px 0 21px}.byline,.reader-actions,.reader-tabs,.note-head,.generation-note{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.byline{font-size:12px;color:var(--muted)}.byline span{font-weight:650;color:var(--accent)}.byline i{font-style:normal}.reader-head h1{font:700 clamp(28px,3.3vw,46px)/1.35 var(--serif);margin:10px 0 18px;overflow-wrap:anywhere}.reader-actions .quiet-action,.reader-actions .primary-action{min-height:33px;font-size:12px;padding:6px 11px}.reader-actions [aria-pressed=true]{color:var(--accent);background:var(--tint)}
.reader-tabs{border-bottom:1px solid var(--line);margin-bottom:16px;gap:16px}.reader-tabs button{padding:8px 3px;border:0;border-bottom:2px solid transparent;background:none;color:var(--muted);font-size:14px}.reader-tabs [aria-pressed=true]{border-bottom-color:var(--accent);color:var(--accent);font-weight:650}
.reader-sheet,.note-panel{background:var(--surface);border:1px solid var(--line);border-radius:8px}.reader-sheet{padding:clamp(20px,4vw,48px);max-width:860px;margin:auto}.reader-sheet :deep(.markdown-body>:first-child){margin-top:0}.reader-sheet :deep(.markdown-body){line-height:1.95}.notes{display:grid;gap:12px}.note-panel{padding:18px 22px}.note-head{justify-content:space-between}.note-panel h2,.note-panel summary{font:650 19px/1.5 var(--serif)}summary{cursor:pointer}.score,.note-panel small,.generation-note{font-size:13px;color:var(--muted)}.generation-note{color:var(--success)}.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 25px;margin:15px 0}.metrics>div{display:flex;gap:7px;align-items:center;font-size:12px}.metrics meter{flex:1;min-width:20px;accent-color:var(--success)}.metrics b{min-width:2ch}.note-panel dl{display:grid;grid-template-columns:max-content 1fr;gap:9px 18px;font-size:14px}.note-panel dt{color:var(--muted)}.note-panel dd{margin:0;overflow-wrap:anywhere}.opinion{margin:12px 0;color:var(--muted)}.regen{justify-self:start}
@media(max-width:600px){.metrics{grid-template-columns:1fr}.note-panel{padding:14px}.reader-back{margin-bottom:12px}.reader-sheet{padding:17px}.reader-head{padding:15px 0}.reader-actions{gap:6px}}
</style>
