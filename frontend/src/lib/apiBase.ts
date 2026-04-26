/**
 * In dev with empty base, relative paths use the Vite proxy. In production, set
 * VITE_API_BASE_URL to the API origin (no trailing slash), e.g. https://api.example.com
 */
export function getApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE_URL
  if (raw === undefined || raw === null || String(raw).trim() === '') {
    return ''
  }
  return String(raw).replace(/\/$/, '')
}

export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const base = getApiBase()
  if (!base) {
    return p
  }
  return `${base}${p}`
}
