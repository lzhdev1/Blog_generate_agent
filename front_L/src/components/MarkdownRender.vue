<template>
  <div ref="root" class="markdown-body" v-html="renderedHtml"></div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { renderMarkdown } from '@/utils/renderMarkdown'
import { useAuthStore } from '@/stores/auth'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

const props = defineProps({
  content: { type: String, default: '' },
  evidence: Array,
  highlightImageMarkers: { type: Boolean, default: false }
})
const { locale } = useI18n()
const auth = useAuthStore()
const root = ref(null)
function mediaPath(src) {
  try {
    const url = new URL(src, document.baseURI)
    return url.origin === location.origin && /^\/images\/[^/]+$/.test(url.pathname) ? url.pathname + url.search : null
  } catch { return null }
}
const renderedHtml = computed(() => renderMarkdown(props.content, {
  evidence: props.evidence,
  highlightImageMarkers: props.highlightImageMarkers,
  markerLabel: locale.value === 'en' ? 'Illustration' : '配图位置',
  mediaPath
}))

const images = new Map()
let currentToken
function release(path, item) {
  item.controller.abort()
  if (item.url) URL.revokeObjectURL(item.url)
  images.delete(path)
}
function syncImages() {
  if (!root.value) return
  if (auth.token !== currentToken) {
    images.forEach((item, path) => release(path, item))
    currentToken = auth.token
  }
  const nodes = root.value.querySelectorAll('img[data-blog-media]')
  const wanted = new Set(Array.from(nodes, element => element.dataset.blogMedia))
  images.forEach((item, path) => { if (!wanted.has(path)) release(path, item) })
  for (const img of nodes) {
    const path = img.dataset.blogMedia
    const entry = images.get(path)
    if (entry?.url) { img.src = entry.url; continue }
    img.removeAttribute('src')
    if (entry) continue
    const item = { controller: new AbortController(), url: null }
    images.set(path, item)
    void loadImage(path, item, currentToken)
  }
}
async function loadImage(path, item, token) {
  try {
    const response = await fetch(path, {
      mode:'same-origin', redirect:'error', cache:'no-store', signal:item.controller.signal,
      headers:token ? { Authorization:`Bearer ${token}` } : {}
    })
    if (!response.ok || !response.headers.get('content-type')?.startsWith('image/')) return
    const blob = await response.blob()
    if (images.get(path) !== item || token !== auth.token) return
    item.url = URL.createObjectURL(blob)
    for (const img of root.value?.querySelectorAll('img[data-blog-media]') || []) {
      if (img.dataset.blogMedia === path) img.src = item.url
    }
  } catch { /* The Markdown alt text remains available if the image is unavailable. */ }
}
onMounted(syncImages)
watch([renderedHtml, () => auth.token], syncImages, { flush:'post' })
onBeforeUnmount(() => images.forEach((item, path) => release(path, item)))
</script>

<style scoped>
.markdown-body { line-height: 1.8; overflow-wrap: anywhere; }
.markdown-body :deep(.image-marker) { display: block; }
</style>
