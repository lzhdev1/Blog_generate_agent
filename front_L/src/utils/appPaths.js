export function apiBase(base = import.meta.env.BASE_URL) {
  return base + 'api/v1'
}

export function protectedMediaPath(src, origin, base = import.meta.env.BASE_URL) {
  try {
    const url = new URL(src, new URL(base, origin))
    if (url.origin !== origin || url.username || url.password) return null
    const path = url.pathname.startsWith(base) ? '/' + url.pathname.slice(base.length) : url.pathname
    if (!/^\/images\/[\w.-]+$/.test(path)) return null
    return base + path.slice(1) + url.search
  } catch { return null }
}
