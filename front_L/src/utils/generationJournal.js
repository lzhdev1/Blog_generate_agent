// A stage submission may be committed even if the browser never receives the response.
// Keep the exact command until the API acknowledges or rejects it.
const stages = {
  'generate-titles': 'title',
  'submit-title-config': 'outline',
  'regenerate-outline': 'outline',
  'generate-content': 'content'
}

export function generationStage(endpoint) {
  return Object.hasOwn(stages, endpoint) ? stages[endpoint] : null
}

export function createGenerationJournal(memory, storage) {
  const keyFor = (owner, taskId) => `blog-agent-request:${owner}:${taskId}`
  return {
    read(owner, taskId) {
      const key = keyFor(owner, taskId)
      if (memory.has(key)) return memory.get(key)
      if (!owner) return null
      try {
        const saved = JSON.parse(storage().getItem(key))
        return saved?.id && generationStage(saved.endpoint) ? saved : null
      } catch { return null }
    },
    save(owner, taskId, record) {
      const key = keyFor(owner, taskId)
      memory.set(key, record)
      if (!owner) return
      try {
        if (record) storage().setItem(key, JSON.stringify(record))
        else storage().removeItem(key)
      } catch { /* Keep the in-memory copy when tab storage is unavailable. */ }
    }
  }
}

export function hasReceipt(record, task) {
  return Boolean(record?.id && task.accepted_request_key === record.id)
}

export function admissionWasRejected(error) {
  const status = error.response?.status
  return (status >= 400 && status < 500 && status !== 408) ||
    (status === 503 && ['queue_full', 'generation_paused', 'site_daily_limit'].includes(error.response?.data?.detail?.code))
}
