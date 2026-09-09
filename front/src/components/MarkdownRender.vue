<template>
  <div class="markdown-body" v-html="renderedHtml"></div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

const props = defineProps({
  content: {
    type: String,
    default: ''
  },
  highlightImageMarkers: {
    type: Boolean,
    default: false
  }
})

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return '<pre><code class="hljs">' +
          hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
          '</code></pre>'
      } catch (__) {}
    }
    return '<pre><code class="hljs">' + md.utils.escapeHtml(str) + '</code></pre>'
  }
})

const renderedHtml = computed(() => {
  if (!props.content) return ''
  let html = md.render(props.content)
  // 高亮配图标记
  if (props.highlightImageMarkers) {
    html = html.replace(/<!--\s*配图[：:]\s*(.+?)\s*-->/g,
      '<div class="image-marker">🖼️ 配图位置：$1</div>')
  }
  return html
})
</script>

<style scoped>
.markdown-body {
  line-height: 1.8;
}
</style>
