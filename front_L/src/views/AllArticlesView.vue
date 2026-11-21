<template>
  <div class="studio-page">
    <header class="page-heading"><div><h1>{{ t('studio.explore') }}</h1><p>{{ t('studio.exploreIntro') }}</p></div></header>
    <div class="index-head">
      <h2>{{ query ? t('studio.results') + ' · ' + query : t('studio.all') }}</h2>
      <router-link v-if="query" class="link-action" to="/articles">{{ t('studio.clear') }}</router-link>
      <small v-else-if="!busy && !error">{{ total }} {{ t('studio.found') }}</small>
    </div>
    <div v-if="busy && !items.length" role="status" class="empty-panel">{{ t('studio.loading') }}</div>
    <div v-else-if="!items.length" class="empty-panel">
      <SvgIcon :name="query ? 'search' : 'library'" :size="29" /><h2>{{ t(error ? 'studio.listError' : query ? 'studio.emptySearch' : 'studio.emptyPublic') }}</h2>
      <p v-if="!error">{{ t(query ? 'studio.searchHint' : 'studio.emptyPublicHint') }}</p>
      <button v-if="error" class="quiet-action" @click="fetchPage(true)">{{ t('studio.retry') }}</button>
    </div>
    <div v-else class="public-grid">
      <article v-for="a in items" :key="a.task_id" class="public-card">
        <div class="card-meta"><span>{{ styleLabel(a) }}</span><small>{{ articleDate(a.created_at,locale) }}</small></div>
        <router-link :to="'/blog/' + a.task_id" class="card-title">{{ a.title }}</router-link>
        <p v-if="a.topic !== a.title" class="subject">{{ a.topic }}</p>
        <div class="card-footer"><span class="author">{{ a.nickname || t('studio.by') }}</span>
          <button :class="{marked:a.liked}" :aria-label="t('studio.like')" :aria-pressed="a.liked" :disabled="pending.has('like'+a.task_id)" @click="interact(a,'like')"><SvgIcon name="like" :size="15" />{{ a.like_count }}</button>
          <button :class="{marked:a.favorited}" :aria-label="t('studio.favorite')" :aria-pressed="a.favorited" :disabled="pending.has('favorite'+a.task_id)" @click="interact(a,'favorite')"><SvgIcon name="star" :size="15" />{{ a.favorite_count }}</button>
          <button v-if="a.allow_download || a.is_demo" class="download-btn" @click="download(a)"><SvgIcon name="download" :size="14" />{{ a.download_price > 0 && !a.is_demo ? '¥' + a.download_price : t('studio.download') }}</button>
        </div>
      </article>
    </div>
    <button v-if="items.length && items.length < total" class="quiet-action load" :disabled="busy" @click="fetchPage(false)">{{ t(busy ? 'studio.loading' : error ? 'studio.retry' : 'studio.more') }}</button>
  </div>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SvgIcon from '@/components/SvgIcon.vue'
import { getArticles, searchArticles, toggleLike, toggleFavorite, downloadArticle } from '@/api/article'
import { articleDate, exportMarkdown } from '@/utils/articles'
const route=useRoute(), router=useRouter()
const { t, locale, te }=useI18n()
const query=computed(() => String(route.query.q || '').trim())
const items=ref([]), total=ref(0), busy=ref(false), error=ref(false)
const pending=reactive(new Set())
let sequence=0
watch(query, () => fetchPage(true), {immediate:true})
function styleLabel(a) { const key = 'studio.style.' + a.article_style; return t(a.is_demo ? 'studio.demo' : te(key) ? key : 'studio.article') }
async function fetchPage(reset) {
  if (!reset && busy.value) return
  const ticket=++sequence
  if (reset) { items.value=[]; total.value=0 }
  busy.value=true
  error.value=false
  try {
    const offset=items.value.length
    const page=query.value ? await searchArticles(query.value,12,offset) : await getArticles({limit:12,offset,random:false})
    if (ticket === sequence) { items.value=[...items.value,...page.items]; total.value=page.total }
  } catch { if (ticket === sequence) error.value=true }
  finally { if (ticket === sequence) busy.value=false }
}
async function interact(a,action) {
  const key=action+a.task_id
  if (pending.has(key)) return
  pending.add(key)
  try {
    if (action === 'like') { const res=await toggleLike(a.task_id); a.liked=res.liked; a.like_count=res.like_count }
    else { const res=await toggleFavorite(a.task_id); a.favorited=res.favorited; a.favorite_count=Math.max(0,a.favorite_count+(res.favorited ? 1 : -1)) }
  } catch { /* Requests provide feedback. */ }
  finally { pending.delete(key) }
}
async function download(a) {
  if (a.download_price > 0 && !a.is_demo) { await router.push('/blog/' + a.task_id); return }
  try { const data=await downloadArticle(a.task_id); exportMarkdown(data.title,data.content) } catch { /* Requests provide feedback. */ }
}
</script>
<style scoped>
.index-head,.card-meta,.card-footer{display:flex;align-items:center;gap:10px}.index-head{padding:14px 0;border-top:1px solid var(--line);justify-content:space-between}.index-head h2{font:650 21px var(--serif);overflow-wrap:anywhere}.index-head small,.card-meta small,.subject,.card-footer{color:var(--muted);font-size:12px}
.public-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:14px}.public-card{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:7px;padding:19px;display:flex;flex-direction:column;align-items:stretch;min-width:0}.card-meta{justify-content:space-between}.card-meta>span{font-size:11px;color:var(--accent);font-weight:650}.card-title{display:block;font:650 22px/1.5 var(--serif);margin:14px 0 8px;overflow-wrap:anywhere}.card-title:hover{color:var(--accent)}.subject{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:12px}.card-footer{border-top:1px solid var(--line);padding-top:12px;margin-top:auto;gap:9px}.author{margin-right:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.card-footer button{display:inline-flex;gap:3px;align-items:center;background:none;border:0;padding:3px 0;color:var(--muted);font-size:12px}.card-footer .marked,.card-footer button:hover{color:var(--accent)}.load{display:flex;margin:22px auto}
</style>
