<template>
  <div class="markdown-body" v-html="renderedHtml"></div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'

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

/**
 * 渲染 LaTeX 数学公式：$$...$$（块级）和 $...$（行内）
 * 先处理块级，再处理行内，避免正则互相干扰
 */
function renderMath(html) {
  if (!html) return html

  // 块级公式 $$...$$（可能跨行）
  html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_, expr) => {
    try {
      return katex.renderToString(expr.trim(), { displayMode: true, throwOnError: false })
    } catch (e) {
      return `<pre>${expr.trim()}</pre>`
    }
  })

  // 行内公式 $...$（不跨行，且排除 $$ 干扰）
  html = html.replace(/(^|[^$])\$([^$\n]+?)\$(?!\$)/g, (_, pre, expr) => {
    try {
      return pre + katex.renderToString(expr.trim(), { displayMode: false, throwOnError: false })
    } catch (e) {
      return pre + '$' + expr.trim() + '$'
    }
  })

  return html
}

const renderedHtml = computed(() => {
  if (!props.content) return ''
  let html = md.render(props.content)
  // 渲染 LaTeX 公式
  html = renderMath(html)
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
