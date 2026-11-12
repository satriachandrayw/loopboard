import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiGet, AuthError } from './api'
import { clearToken, setToken } from './token'

function stub(status = 200) {
  const f = vi.fn(async () => new Response('{"ok":true}', { status }))
  vi.stubGlobal('fetch', f)
  return f
}
beforeEach(() => clearToken())
afterEach(() => vi.unstubAllGlobals())

it('test_bearer_header_sent_when_token_set', async () => {
  const f = stub()
  setToken('lb_abc')
  await apiGet('/api/board')
  const init = f.mock.calls[0] as unknown as [string, RequestInit]
  expect(new Headers(init[1].headers).get('Authorization')).toBe('Bearer lb_abc')
})

it('test_no_header_without_token', async () => {
  const f = stub()
  await apiGet('/api/board')
  const init = f.mock.calls[0] as unknown as [string, RequestInit]
  expect(new Headers(init[1].headers).has('Authorization')).toBe(false)
})

it('test_401_throws_AuthError', async () => {
  stub(401)
  await expect(apiGet('/api/board')).rejects.toBeInstanceOf(AuthError)
})
