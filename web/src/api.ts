import { getToken } from './token'

export class AuthError extends Error {
  constructor() {
    super('unauthorized')
    this.name = 'AuthError'
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number) {
    super(`request failed: ${status}`)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Writes always send a JSON body: the API requires application/json on bodiless
  // POSTs (confirm-done) so a cross-site form cannot ride the Access cookie.
  if (method !== 'GET' && body === undefined) body = {}
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) throw new AuthError()
  if (!res.ok) throw new ApiError(res.status)
  return (await res.json()) as T
}

export const apiGet = <T>(path: string) => request<T>('GET', path)
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, body)
export const apiPatch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body)
export const apiPut = <T>(path: string, body: unknown) => request<T>('PUT', path, body)
