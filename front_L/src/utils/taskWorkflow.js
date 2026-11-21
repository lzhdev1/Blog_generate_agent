const titleStates = ['pending', 'researching_title', 'generating_titles', 'reviewing_title', 'title_generated']
const outlineStates = ['researching_outline', 'generating_outline', 'reviewing_outline', 'outline_generated']

export const activeTaskStates = new Set([
  ...titleStates.slice(1, -1), ...outlineStates.slice(0, -1),
  'researching_content', 'generating_content', 'reviewing', 'generating_images', 'formatting'
])

export function taskPath(task) {
  const id = task.id ?? task.task_id
  // content_generated is the terminal status used by older, pre-formatting tasks.
  if (['completed', 'content_generated'].includes(task.status)) return `/blog/${id}`
  if (task.status === 'failed') {
    if (task.job?.stage === 'title') return `/task/${id}/titles`
    if (task.job?.stage === 'outline') return `/task/${id}/outline`
    if (task.job?.stage === 'content') return `/task/${id}/generating`
    if (!('outline_confirmed' in task) || task.outline_confirmed) return `/task/${id}/generating`
    return `/task/${id}/${task.selected_title ? 'outline' : 'titles'}`
  }
  if (titleStates.includes(task.status)) return `/task/${id}/titles`
  if (outlineStates.includes(task.status) && !(task.status === 'outline_generated' && task.outline_confirmed)) {
    return `/task/${id}/outline`
  }
  return `/task/${id}/generating`
}

export function researchSummary(text) {
  if (!text) return ''
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object') {
      return [parsed.observation, parsed.summary].filter(Boolean).join('\n\n')
    }
  } catch { /* Earlier versions store the research as plain Markdown. */ }
  if (text.includes('【思考】')) {
    return ['观察', '总结'].map(label => text.match(new RegExp(`【${label}】([\\s\\S]*?)(?=【|$)`))?.[1]?.trim()).filter(Boolean).join('\n\n')
  }
  return text
}
