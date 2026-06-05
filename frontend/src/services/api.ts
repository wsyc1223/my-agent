const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL || ''

export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, '')

export function apiUrl(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`
}

export function getAuthHeaders() {
  const token = localStorage.getItem('token')
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}
