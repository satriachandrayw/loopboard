import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { clearToken } from './token'

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })
beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })

it('test_malformed_epic_hash_falls_back_to_board', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ columns: [] })))
  window.location.hash = '#/epic/%E0%A4%A'
  render(<App />)
  await waitFor(() => expect(screen.getByLabelText('Project')).toBeTruthy())
})
