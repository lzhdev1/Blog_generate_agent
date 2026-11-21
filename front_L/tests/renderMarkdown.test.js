import test from 'node:test'
import assert from 'node:assert/strict'
import { renderMarkdown } from '../src/utils/renderMarkdown.js'

test('only citations present in a manuscript’s source list become links in prose', () => {
  const evidence = [{ id:'S1', title:'Source', url:'https://example.com/a' }, { id:'S2', url:'data:,invalid' }]
  const html = renderMarkdown('First [S1]. Unknown [S2]. Literal `[S1]`.', { evidence })
  assert.equal((html.match(/href=/g) || []).length, 1)
  assert.match(html, /href="https:\/\/example.com\/a"/)
  assert.match(html, /Unknown \[S2\]/)
  assert.match(html, /<code>\[S1\]<\/code>/)
  assert.doesNotMatch(renderMarkdown('First [S1].'), /href=/)
  const conflictingDefinition = renderMarkdown('Source [s1].\n\n[S1]: https://example.com/b', { evidence })
  assert.match(conflictingDefinition, /href="https:\/\/example.com\/a"/)
  assert.doesNotMatch(conflictingDefinition, /href="https:\/\/example.com\/b"/)
})

test('article prose and illustration descriptions both escape raw HTML', () => {
  const content = '<b>Draft</b>\n\n<!-- 配图：<em>河面</em> -->'
  const html = renderMarkdown(content, { highlightImageMarkers: true })
  assert.match(html, /&lt;b&gt;Draft&lt;\/b&gt;/)
  assert.match(html, /class="image-marker">配图位置 &lt;em&gt;河面&lt;\/em&gt;/)
  assert.doesNotMatch(renderMarkdown(content), /image-marker|河面/)
})

test('formulas render in prose and never inside fenced or inline code', () => {
  const html = renderMarkdown([
    'Inline $x+1$ and `$code$`.', '', '$$', 'a+b', '$$', '',
    '~~~text', '$code$ <!-- 配图：literal -->', '~~~'
  ].join('\n'), { highlightImageMarkers: true })
  assert.equal((html.match(/class="katex"/g) || []).length, 2)
  assert.match(html, /class="katex-display"/)
  assert.match(html, /<code>\$code\$<\/code>/)
  assert.match(html, /\$code\$ &lt;!-- 配图：literal --&gt;/)
  assert.doesNotMatch(html, /image-marker/)
})

test('links, image URLs, money and escaped dollar signs are preserved', () => {
  const html = renderMarkdown(String.raw`[Source](https://example.com/read "Cost $x$") ![River](/images/a.jpg) costs $5 to $10. \$x\$`)
  assert.match(html, /href="https:\/\/example.com\/read" title="Cost \$x\$"/)
  assert.match(html, /<img src="\/images\/a.jpg" alt="River">/)
  assert.match(html, /costs \$5 to \$10\. \$x\$/)
  assert.doesNotMatch(html, /class="katex"/)
})

test('protected media URLs are never emitted as native image requests', () => {
  const html = renderMarkdown('![Private](/images/task9_1.jpg) ![Public](https://example.com/photo.jpg)', {
    mediaPath: src => src.startsWith('/images/') ? src : null
  })
  assert.match(html, /<img data-blog-media="\/images\/task9_1.jpg" alt="Private">/)
  assert.doesNotMatch(html, /src="\/images\//)
  assert.match(html, /<img src="https:\/\/example.com\/photo.jpg" alt="Public">/)
})
