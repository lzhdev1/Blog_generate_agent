import MarkdownIt from 'markdown-it'
import katex from 'katex'
import { shallowRef } from 'vue'
import { evidenceSources } from './evidenceSources.js'

// Render the plain code immediately. Mounted Markdown previews recompute when
// the complete language registry arrives, including languages outside "common".
const highlighter = shallowRef(null)
let loadingHighlighter

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight(code, lang) {
    if (!lang) return ''
    if (!highlighter.value) {
      loadingHighlighter ??= import('highlight.js')
        .then(module => { highlighter.value = module.default })
        .catch(() => { loadingHighlighter = undefined })
      return ''
    }
    if (!highlighter.value.getLanguage(lang)) return ''
    return '<pre><code class="hljs">' + highlighter.value.highlight(code, { language: lang, ignoreIllegals: true }).value + '</code></pre>'
  }
})

// Parse these delimiters while Markdown still knows which text belongs to a
// code fence, an inline code span, a link destination or ordinary prose.
const marker = /<!--\s*配图[：:]\s*([\s\S]*?)\s*-->/y
const inlineMath = /\$(?![\s$])((?:\\[^\n]|[^$\\\n])+?)(?<!\s)\$(?!\d)/y
const displayInParagraph = /\$\$((?:\\[^\n]|[^$\\\n]|\$(?!\$))+?)\$\$/y

function tokenRule(type, pattern) {
  return (state, silent) => {
    pattern.lastIndex = state.pos
    const match = pattern.exec(state.src)
    if (!match || pattern.lastIndex > state.posMax) return false
    if (!silent) state.push(type, '', 0).content = match[1].trim()
    state.pos = pattern.lastIndex
    return true
  }
}

md.inline.ruler.before('html_inline', 'image_marker', tokenRule('image_marker', marker))
const sourceMarker = /\[(S[1-9]\d*)\](?!\()/iy
md.inline.ruler.before('link', 'evidence_citation', (state, silent) => {
  if (state.linkLevel || state.src[state.pos] !== '[' || !state.env.sources?.size) return false
  sourceMarker.lastIndex = state.pos
  const match = sourceMarker.exec(state.src)
  const source = match && state.env.sources.get(match[1].toUpperCase())
  if (!source || sourceMarker.lastIndex > state.posMax) return false
  if (!silent) {
    const link = state.push('link_open', 'a', 1)
    link.attrs = [['href', source.url], ['target', '_blank'], ['rel', 'noopener noreferrer'], ['title', source.title || source.site]]
    state.push('text', '', 0).content = match[0]
    state.push('link_close', 'a', -1)
  }
  state.pos = sourceMarker.lastIndex
  return true
})
md.inline.ruler.before('text', 'display_math_inline', tokenRule('display_math', displayInParagraph))
md.inline.ruler.before('text', 'inline_math', tokenRule('inline_math', inlineMath))

md.block.ruler.before('fence', 'display_math', (state, start, end, silent) => {
  if (state.sCount[start] - state.blkIndent >= 4) return false
  const line = state.src.slice(state.bMarks[start] + state.tShift[start], state.eMarks[start]).trimEnd()
  if (!line.startsWith('$$')) return false
  // A same-line pair is already handled by the inline rule, including surrounding prose.
  if (line.slice(2).includes('$$')) return false
  let last = start + 1
  for (; last < end; last++) {
    if (!state.isEmpty(last) && state.sCount[last] < state.blkIndent) return false
    const tail = state.src.slice(state.bMarks[last] + state.tShift[last], state.eMarks[last]).trimEnd()
    if (tail.endsWith('$$')) break
  }
  if (last >= end) return false
  if (silent) return true
  const token = state.push('display_math', '', 0)
  token.map = [start, last + 1]
  token.content = state.getLines(start, last + 1, state.blkIndent, false).trim().slice(2, -2).trim()
  state.line = last + 1
  return true
}, { alt: ['paragraph', 'reference', 'blockquote', 'list'] })

function renderMath(tokens, index) {
  const token = tokens[index]
  try {
    return katex.renderToString(token.content, {
      displayMode: token.type === 'display_math', trust: false, throwOnError: false
    })
  } catch {
    return '<code>' + md.utils.escapeHtml(token.content) + '</code>'
  }
}
md.renderer.rules.inline_math = renderMath
md.renderer.rules.display_math = renderMath
const renderImage = md.renderer.rules.image
md.renderer.rules.image = (tokens, index, options, env, renderer) => {
  const token = tokens[index]
  const path = env.mediaPath?.(token.attrGet('src'))
  if (path) {
    // No src is emitted until the credentialed request succeeds.
    token.attrs[token.attrIndex('src')] = ['data-blog-media', path]
  }
  return renderImage(tokens, index, options, env, renderer)
}
md.renderer.rules.image_marker = (tokens, index, options, env) => {
  if (!env.highlightImageMarkers) return ''
  return '<span class="image-marker">' + md.utils.escapeHtml(env.markerLabel + ' ' + tokens[index].content) + '</span>'
}

export function renderMarkdown(content, { highlightImageMarkers = false, markerLabel = '配图位置', mediaPath, evidence } = {}) {
  const sources = new Map(evidenceSources(evidence).map(source => [source.id, source]))
  return md.render(content || '', { highlightImageMarkers, markerLabel, mediaPath, sources })
}
