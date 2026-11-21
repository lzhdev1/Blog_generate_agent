export function exportMarkdown(title, content) {
  const url = URL.createObjectURL(new Blob([content || ''], {type:'text/markdown;charset=utf-8'}))
  const link = document.createElement('a')
  link.href = url
  link.download = (title || 'article').replace(/[\\/:*?"<>|]/g, '-') + '.md'
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url),1000)
}

export function articleDate(value, locale) {
  if (!value) return ''
  // API timestamps originate from UTC, including historical offset-free values.
  const iso = /^\d{4}-\d\d-\d\dT\d\d:\d\d:.*\d$/.test(value) && !/[+-]\d\d:\d\d$/.test(value) ? value + 'Z' : value
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en',{year:'numeric',month:'short',day:'numeric'}).format(date)
}

export function withoutDuplicateTitle(content = '', title = '') {
  const text = content || ''
  const heading = text.match(/^\s*#\s+([^\n]+)\n?/)
  return heading && heading[1].trim() === title?.trim() ? text.slice(heading[0].length).trimStart() : text
}
