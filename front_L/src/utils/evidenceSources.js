export function evidenceSources(records) {
  const entries = []
  for (const record of records || []) {
    if (!/^S[1-9]\d*$/.test(record?.id)) continue
    try {
      const url = new URL(record.url)
      if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) {
        entries.push({ ...record, url:url.href, site:record.site || url.hostname })
      }
    } catch { /* Historical records may contain incomplete URLs. */ }
  }
  return entries
}
