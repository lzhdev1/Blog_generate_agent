<template>
  <div class="studio-page library">
    <header class="page-heading"><div><h1>{{ t('studio.library') }}</h1><p>{{ t('studio.libraryIntro') }}</p></div><router-link to="/" class="primary-action"><SvgIcon name="plus" :size="16" />{{ t('studio.newDraft') }}</router-link></header>
    <nav class="collections" :aria-label="t('studio.library')">
      <router-link v-for="tab in tabs" :key="tab" :to="{path:'/my-articles', query:tab === 'created' ? {} : {tab}}" :class="{active:tab === active}" :aria-current="tab === active ? 'page' : undefined">{{ t('studio.tabs.' + tab) }}</router-link>
    </nav>
    <div v-if="busy && !items.length" class="empty-panel" role="status">{{ t('studio.loading') }}</div>
    <div v-else-if="!items.length" class="empty-panel"><SvgIcon name="library" :size="28" /><h2>{{ t(error ? 'studio.listFail' : 'studio.noItems') }}</h2><p v-if="!error">{{ t(active === 'created' ? 'studio.noCreated' : 'studio.noSaved') }}</p><button v-if="error" class="quiet-action" @click="fetchPage(true)">{{ t('studio.retry') }}</button><router-link v-else :to="active === 'created' ? '/' : '/articles'" class="quiet-action">{{ t(active === 'created' ? 'studio.newDraft' : 'studio.explore') }}</router-link></div>
    <div v-else class="article-rows">
      <router-link v-for="a in items" :key="a.record_id || a.task_id" :to="target(a)" class="article-row">
        <span class="file-icon"><SvgIcon :name="active === 'favorited' ? 'star' : 'document'" :size="22" /></span>
        <span class="row-copy"><strong>{{ a.title || a.topic }}</strong><small>{{ articleDate(a.created_at,locale) }}<template v-if="a.purchased_price != null"> · ¥{{ a.purchased_price }}</template><template v-if="active === 'created'"> · {{ t(a.is_public ? 'studio.public' : 'studio.private') }}</template></small></span>
        <span v-if="active === 'created'" class="phase" :class="{done:a.status === 'completed'}">{{ t(a.job_status === 'queued' ? 'studio.queued' : 'studio.status.' + a.status) }}</span>
        <SvgIcon name="right" :size="17" />
      </router-link>
    </div>
    <button v-if="items.length && items.length < total" class="quiet-action load" :disabled="busy" @click="fetchPage(false)">{{ t(busy ? 'studio.loading' : error ? 'studio.retry' : 'studio.more') }}</button>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SvgIcon from '@/components/SvgIcon.vue'
import { getMyArticles } from '@/api/article'
import { taskPath } from '@/utils/taskWorkflow'
import { articleDate } from '@/utils/articles'
const route = useRoute()
const { t, locale } = useI18n()
const tabs = ['created','liked','favorited','purchased','downloaded']
const active = computed(() => tabs.includes(route.query.tab) ? route.query.tab : 'created')
const items = ref([]), total = ref(0), busy = ref(false), error = ref(false)
let sequence = 0
watch(active, () => fetchPage(true), { immediate:true })
async function fetchPage(reset) {
  if (!reset && busy.value) return
  const ticket = ++sequence
  if (reset) { items.value = []; total.value = 0 }
  busy.value = true
  error.value = false
  try {
    const page = await getMyArticles(active.value, { limit:24, offset:items.value.length })
    if (ticket === sequence) { items.value = [...items.value, ...page.items]; total.value = page.total }
  } catch { if (ticket === sequence) error.value = true }
  finally { if (ticket === sequence) busy.value = false }
}
function target(a) {
  if (active.value === 'created') return taskPath(a)
  if (a.record_id && ['purchased','downloaded'].includes(active.value)) return '/library/' + active.value + '/' + a.record_id
  return '/blog/' + a.task_id
}
</script>
<style scoped>
.collections {display:flex;overflow-x:auto;gap:8px;margin:14px 0 20px;border-bottom:1px solid var(--line)}.collections a {white-space:nowrap;font-size:14px;padding:10px 13px;color:var(--muted);border-bottom:2px solid transparent}.collections a.active {border-color:var(--accent);color:var(--accent);font-weight:650}
.article-rows{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}.article-row{display:flex;align-items:center;gap:16px;padding:18px}.article-row+a{border-top:1px solid var(--line)}.article-row:hover{background:var(--soft)}
.file-icon{width:39px;height:45px;border-radius:4px;display:grid;place-items:center;color:var(--muted);background:var(--soft)}.row-copy{display:grid;gap:5px;flex:1;min-width:0}.row-copy strong{font:650 18px/1.45 var(--serif);overflow-wrap:anywhere}.row-copy small{font-size:12px;color:var(--muted)}
.phase{color:var(--accent);background:var(--tint);border-radius:4px;padding:2px 7px;font-size:12px}.phase.done{color:var(--success);background:var(--soft)}.load{display:flex;margin:20px auto}
@media(max-width:600px){.collections{gap:0}.collections a{font-size:13px;padding:8px}.article-row{gap:8px;padding:12px}.row-copy strong{font-size:15px}.file-icon{display:none}.phase{font-size:10px}}
</style>
