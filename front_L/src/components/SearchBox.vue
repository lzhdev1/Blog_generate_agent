<template>
  <div ref="wrap" class="search-box" @focusout="onBlur">
    <form class="search-input-wrap" role="search" @submit.prevent="submit">
      <SvgIcon name="search" :size="16" aria-hidden="true" />
      <input ref="input" v-model="keyword" class="search-input" type="text" role="combobox"
        autocomplete="off" enterkeyhint="search" aria-autocomplete="list" :aria-expanded="open"
        :aria-controls="open ? 'article-suggestions' : undefined"
        :aria-activedescendant="open && active >= 0 ? 'article-suggestion-' + active : undefined"
        :aria-label="t('studio.search')" :placeholder="t('nav.searchPlaceholder')"
        @focus="schedule" @input="changed" @compositionstart="close" @keydown="onKey" />
      <button v-if="keyword" type="button" class="search-clear" :aria-label="t('studio.clear')" @mousedown.prevent @click="clear">
        <SvgIcon name="close" :size="13" />
      </button>
    </form>
    <Teleport to="body">
      <div v-if="open" ref="dropdown" class="search-dropdown" :style="position" @focusout="onBlur">
        <div class="search-status" role="status">
          {{ loading ? t('nav.searching') : failed ? t('studio.listError') : results.length ? t('nav.searchResults') : t('nav.noResults') }}
        </div>
        <ul id="article-suggestions" role="listbox" :aria-label="t('nav.searchResults')">
          <li v-for="(article, index) in results" :id="'article-suggestion-' + index" :key="article.task_id"
            role="option" :aria-selected="active === index" :class="{ active: active === index }"
            @mousedown.prevent @click="goArticle(article)">
            <span class="suggestion-type">{{ article.is_demo ? t('studio.demo') : (article.nickname || t('studio.article')) }}</span>
            <strong>{{ article.title || article.topic }}</strong>
          </li>
        </ul>
        <button class="show-results" type="button" @mousedown.prevent @click="goSearch">
          <span>{{ fullSearch }}</span><span aria-hidden="true">↵</span>
        </button>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { searchArticles } from '@/api/article'
import SvgIcon from './SvgIcon.vue'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const wrap = ref(null)
const input = ref(null)
const dropdown = ref(null)
const keyword = ref('')
const results = ref([])
const loading = ref(false)
const failed = ref(false)
const open = ref(false)
const active = ref(-1)
const position = ref({})
const fullSearch = computed(() => locale.value === 'en' ? 'Search all articles' : '搜索全部文章')
let timer
let requestNumber = 0

function reposition() {
  if (!open.value || !wrap.value) return
  const rect = wrap.value.getBoundingClientRect()
  const width = Math.min(Math.max(rect.width, 320), document.documentElement.clientWidth - 16)
  const left = Math.min(Math.max(8, rect.left), document.documentElement.clientWidth - width - 8)
  position.value = {
    top: (rect.bottom + 6) + 'px', left: left + 'px', width: width + 'px',
    maxHeight: Math.max(90, Math.min(390, window.innerHeight - rect.bottom - 16)) + 'px'
  }
}
function close() {
  clearTimeout(timer)
  requestNumber++
  open.value = false
  loading.value = false
  active.value = -1
}
function schedule() {
  close()
  const query = keyword.value.trim()
  if (!query) return
  const version = requestNumber
  results.value = []
  open.value = true
  failed.value = false
  loading.value = true
  reposition()
  timer = setTimeout(async () => {
    try {
      const response = await searchArticles(query)
      if (version === requestNumber) results.value = response.items || []
    } catch {
      if (version === requestNumber) failed.value = true
    } finally {
      if (version === requestNumber) loading.value = false
    }
  }, 220)
}
function changed(event) {
  if (!event.isComposing) schedule()
}
function clear() {
  keyword.value = ''
  close()
  input.value?.focus()
}
function goArticle(article) {
  close()
  input.value?.blur()
  router.push('/blog/' + article.task_id)
}
function goSearch() {
  const q = keyword.value.trim()
  if (!q) return
  close()
  input.value?.blur()
  router.push({path: '/articles', query: { q }})
}
function submit() {
  if (open.value && results.value[active.value]) goArticle(results.value[active.value])
  else goSearch()
}
function onKey(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Escape') { close(); return }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  event.preventDefault()
  if (!open.value) { schedule(); return }
  const count = results.value.length
  if (!count) return
  const start = active.value < 0 && event.key === 'ArrowUp' ? 0 : active.value
  active.value = (start + (event.key === 'ArrowDown' ? 1 : -1) + count) % count
  nextTick(() => dropdown.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }))
}
function onBlur(event) {
  if (!wrap.value?.contains(event.relatedTarget) && !dropdown.value?.contains(event.relatedTarget)) close()
}
function outside(event) {
  if (!wrap.value?.contains(event.target) && !dropdown.value?.contains(event.target)) close()
}
watch(() => route.fullPath, () => {
  close()
  keyword.value = route.name === 'AllArticles' && typeof route.query.q === 'string' ? route.query.q : ''
}, { immediate: true })
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('resize', reposition)
  window.addEventListener('scroll', reposition, true)
})
onBeforeUnmount(() => {
  close()
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', reposition)
  window.removeEventListener('scroll', reposition, true)
})
</script>

<style scoped>
.search-box { position: relative; min-width: 0; }
.search-input-wrap { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 10px; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; color: var(--muted); }
.search-input-wrap:focus-within { border-color: var(--accent); }
.search-input { flex: 1; min-width: 0; border: none; outline: none; background: transparent; font: inherit; font-size: 13px; color: var(--ink); }
.search-clear { display: grid; place-items: center; width: 21px; height: 21px; padding: 0; border: 0; border-radius: 4px; color: var(--muted); background: transparent; cursor: pointer; }
.search-clear:hover { background: var(--soft); }
.search-dropdown { position: fixed; z-index: 110; overflow: auto; overscroll-behavior: contain; box-sizing: border-box; border: 1px solid var(--line); border-radius: 8px; padding: 6px; background: var(--surface); color: var(--ink); box-shadow: var(--shadow-md); }
.search-status { font-size: 12px; padding: 8px 10px; color: var(--muted); }
.search-dropdown ul { list-style: none; margin: 0; padding: 0; }
.search-dropdown li { display: flex; align-items: baseline; gap: 10px; padding: 9px 10px; border-radius: 4px; cursor: pointer; }
.search-dropdown li:hover, .search-dropdown li.active { background: var(--soft); }
.search-dropdown li strong { min-width: 0; font-size: 13px; font-weight: 550; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.suggestion-type { flex-shrink: 0; max-width: 6em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--muted); }
.show-results { display: flex; width: 100%; justify-content: space-between; gap: 8px; margin-top: 3px; padding: 10px; background: transparent; border: 0; border-top: 1px solid var(--line); color: var(--accent); font-size: 13px; cursor: pointer; }
</style>
