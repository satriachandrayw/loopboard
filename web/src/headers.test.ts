import { expect, test } from 'vitest'
import headers from '../public/_headers?raw'

test('_headers sets CSP and nosniff for all paths', () => {
  const lines = headers.split('\n').map((l) => l.trim())
  expect(lines).toContain('/*')
  expect(lines).toContain("Content-Security-Policy: default-src 'self'; frame-ancestors 'none'")
  expect(lines).toContain('X-Content-Type-Options: nosniff')
})
