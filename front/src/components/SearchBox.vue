<template>
  <div class="search-box" ref="wrapRef">
    <div class="search-input-wrap">
      <span class="search-icon">
        <SvgIcon name="search" :size="16" />
      </span>
      <input
        v-model="keyword"
        class="search-input"
        type="text"
        :placeholder="$t('nav.searchPlaceholder')"
        @focus="onFocus"
        @input="onInput"
        @keydown.enter="onEnter"
        @keydown.esc="close"
      />
      <span v-if="loading" class="search-loading">
        <SvgIcon name="loading" :size="14" class="animate-spin" />
      </span>
      <button v-else-if="keyword" class="search-clear" title="清空" @click="clearKeyword">
        <SvgIcon name="close" :size="12" />
      </button>
    </div>

    <!-- 下拉结果：Teleport 到 body，避开导航栏 backdrop-filter 的渲染裁剪 -->
    <Teleport to="body">
      <div
        v-if="open && keyword.trim()"
        class="search-dropdown"
        :style="dropdownStyle"
      >
        <div v-if="loading" class="search-empty">
          <SvgIcon name="loading" :size="18" class="animate-spin" />
          <span>{{ $t('nav.searching') }}</span>
        </div>
        <template v-else-if="results.length">
          <div class="search-result-title">{{ $t('nav.searchResults') }}（{{ results.length }}）</div>
          <div
            v-for="(a, i) in results"
            :key="a.task_id"
            class="search-result-item"
            :class="{ active: activeIndex === i }"
            @mousedown.prevent="goArticle(a)"
            @mouseenter="activeIndex = i"
          >
            <div class="result-main">
              <span class="result-tag" :class="a.is_demo ? 'is-demo' : 'is-user'">
                {{ a.is_demo ? $t('home.demo') : $t('home.user') }}
              </span>
              <span class="result-title">{{ a.title }}</span>
            </div>
            <div class="result-sub">
              <span class="result-topic">{{ a.topic }}</span>
              <span class="result-price" :class="a.download_price > 0 ? 'is-paid' : 'is-free'">
                {{ a.download_price > 0 ? `¥${a.download_price}` : $t('home.free') }}
              </span>
            </div>
          </div>
          <div class="search-footer">
            <span>{{ $t('nav.enterToOpen') }}</span>
          </div>
        </template>
        <div v-else class="search-empty">
          <SvgIcon name="search" :size="18" />
          <span>{{ $t('nav.noResults') }}</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { searchArticles } from '@/api/article'
import SvgIcon from '@/components/SvgIcon.vue'

const router = useRouter()
const wrapRef = ref(null)
const keyword = ref('')
const results = ref([])
const loading = ref(false)
const open = ref(false)
const activeIndex = ref(-1)
const dropdownStyle = ref({ top: '0px', left: '0px', width: '320px' })
let debounceTimer = null
let seq = 0

function updateDropdownPos() {
  const el = wrapRef.value?.querySelector('.search-input-wrap')
  if (!el) return
  const r = el.getBoundingClientRect()
  dropdownStyle.value = {
    top: Math.round(r.bottom + 8) + 'px',
    left: Math.round(r.left) + 'px',
    width: Math.round(r.width) + 'px'
  }
}

function onInput() {
  clearTimeout(debounceTimer)
  activeIndex.value = -1
  const q = keyword.value.trim()
  if (!q) {
    open.value = false
    results.value = []
    return
  }
  open.value = true
  updateDropdownPos()
  debounceTimer = setTimeout(() => doSearch(q), 280)
}

async function doSearch(q) {
  const my = ++seq
  loading.value = true
  try {
    const res = await searchArticles(q)
    if (my !== seq) return // 过期响应丢弃
    results.value = res.items || []
    open.value = true
    nextTick(updateDropdownPos)
  } catch (e) {
    if (my === seq) {
      results.value = []
      open.value = true
    }
    console.error('搜索失败:', e)
  } finally {
    if (my === seq) loading.value = false
  }
}

function onFocus() {
  if (keyword.value.trim() && results.value.length) {
    open.value = true
    updateDropdownPos()
  }
}

function onEnter() {
  const q = keyword.value.trim()
  if (!q) return
  if (activeIndex.value >= 0 && results.value[activeIndex.value]) {
    goArticle(results.value[activeIndex.value])
  } else if (results.value.length) {
    goArticle(results.value[0])
  } else {
    // 无结果直接回车：跳到全部文章页
    router.push({ path: '/articles', query: { q } })
    close()
  }
}

function goArticle(a) {
  close()
  router.push(`/blog/${a.task_id}`)
}

function clearKeyword() {
  keyword.value = ''
  results.value = []
  open.value = false
}

function close() {
  open.value = false
  activeIndex.value = -1
}

function onClickOutside(e) {
  if (wrapRef.value && !wrapRef.value.contains(e.target)) close()
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
  document.addEventListener('keydown', onEsc)
  window.addEventListener('scroll', onScrollOrResize, true)
  window.addEventListener('resize', onScrollOrResize)
})
onBeforeUnmount(() => {
  clearTimeout(debounceTimer)
  document.removeEventListener('click', onClickOutside)
  document.removeEventListener('keydown', onEsc)
  window.removeEventListener('scroll', onScrollOrResize, true)
  window.removeEventListener('resize', onScrollOrResize)
})

function onScrollOrResize() {
  if (open.value && keyword.value.trim()) updateDropdownPos()
}

function onEsc(e) {
  if (e.key === 'Escape') close()
}

nextTick(() => {})
</script>

<style scoped>
.search-box {
  position: relative;
  flex: 1;
  max-width: 420px;
  min-width: 0;
  margin: 0 16px;
}

.search-input-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 12px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 999px;
  transition: all 0.2s ease;
}

.search-input-wrap:focus-within {
  border-color: var(--primary);
  background: var(--bg-card);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.search-icon {
  display: flex;
  align-items: center;
  color: var(--text-muted);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  color: var(--text-primary);
}

.search-input::placeholder {
  color: var(--text-muted);
}

.search-loading {
  display: flex;
  align-items: center;
  color: var(--text-muted);
  flex-shrink: 0;
}

.search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: var(--border);
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
}

.search-clear:hover {
  background: var(--text-muted);
  color: #fff;
}

/* 下拉（Teleport 到 body，fixed 定位） */
.search-dropdown {
  position: fixed;
  max-height: 360px;
  overflow-y: auto;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.12);
  z-index: 9999;
  padding: 6px;
  box-sizing: border-box;
}

.search-result-title {
  font-size: 12px;
  color: var(--text-muted);
  padding: 6px 10px 4px;
}

.search-result-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.search-result-item:hover,
.search-result-item.active {
  background: var(--bg-soft);
}

.result-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.result-tag {
  flex-shrink: 0;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  font-weight: 600;
}

.result-tag.is-demo {
  background: var(--bg-soft);
  color: var(--text-secondary);
}

.result-tag.is-user {
  background: rgba(99, 102, 241, 0.1);
  color: var(--primary);
}

.result-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-sub {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  min-width: 0;
}

.result-topic {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-price {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
}

.result-price.is-free {
  background: #ecfdf5;
  color: #059669;
}

.result-price.is-paid {
  background: #fff7ed;
  color: #ea580c;
}

.search-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 12px;
  color: var(--text-muted);
  font-size: 13px;
}

.search-footer {
  padding: 6px 10px 4px;
  font-size: 12px;
  color: var(--text-muted);
  border-top: 1px solid var(--border);
  margin-top: 4px;
}

/* 移动端 */
@media (max-width: 640px) {
  .search-box {
    display: none;
  }
}
</style>
