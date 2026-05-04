const API_VERSION_PREFIX = '/api/v1'

export function getApiBase(): string {
  return ''
}

export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const versionedPath = p.startsWith('/api/') ? p : `${API_VERSION_PREFIX}${p}`
  const base = getApiBase()
  if (!base) {
    return versionedPath
  }
  return `${base}${versionedPath}`
}

export function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(input), init)
}
