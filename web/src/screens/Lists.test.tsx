import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NeedsYou from './NeedsYou'
import Stalled from './Stalled'
import Unfiled from './Unfiled'
import { clearToken } from '../token'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('test_needs_you_renders_server_order_with_reasons', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json([
    { kind: 'epic', id: 1, ref: 'DEMO-E1', title: 'First', waiting_on: 'human:o', waiting_since: 1, reasons: ['waiting on you', 'awaiting your approval'] },
    { kind: 'item', id: 9, ref: 'kanban:9', title: 'Second', url: 'https://x.test/9', waiting_on: 'human:o', waiting_since: 2, reasons: ['waiting on you'] },
  ])))
  render(<NeedsYou />)
  await waitFor(() => screen.getByText('First'))
  const items = screen.getAllByRole('listitem')
  expect(items[0].textContent).toContain('First')
  expect(items[1].textContent).toContain('Second')
  expect(items[0].textContent).toContain('awaiting your approval')
  expect(screen.getByText('First').closest('a')?.getAttribute('href')).toBe('#/epic/DEMO-E1')
  expect(screen.getByText('Second').closest('a')?.getAttribute('href')).toBe('https://x.test/9')
})

it('test_stalled_groups_by_waiting_group', async () => {
  const row = (id: number, g: string, title: string) => ({ kind: 'item', id, ref: `k:${id}`, title, waiting_on: null, waiting_group: g, waiting_since: 1, stalled_for_hours: 5, url: null })
  vi.stubGlobal('fetch', vi.fn(async () => json([row(1, 'source', 'S1'), row(2, 'agent', 'A1'), row(3, 'human', 'H1'), row(4, 'agent', 'A2')])))
  render(<Stalled />)
  await waitFor(() => screen.getByText('A1'))
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Waiting on agent', 'Waiting on you', 'Waiting on source'])
  const agent = screen.getByText('Waiting on agent').closest('section')!
  expect(agent.textContent).toContain('A1')
  expect(agent.textContent).toContain('A2')
  expect(agent.textContent).not.toContain('H1')
})

const unfiled = [{ id: 3, source: 'kanban', external_id: 'a', title: 'Loose', url: null, owner: null, waiting_on: null, last_activity_at: 1 }]

it('test_unfiled_file_to_epic_posts_filing_body', async () => {
  const f = vi.fn(async (_u: string, i?: RequestInit) => (i?.method === 'POST' ? json({}) : json(unfiled)))
  vi.stubGlobal('fetch', f)
  render(<Unfiled />)
  await waitFor(() => screen.getByText('Loose'))
  await userEvent.type(screen.getByLabelText('Epic key for Loose'), 'DEMO-E1')
  await userEvent.click(screen.getByRole('button', { name: 'File to epic' }))
  await waitFor(() => expect(f.mock.calls.some((c) => c[1]?.method === 'POST')).toBe(true))
  const call = f.mock.calls.find((c) => c[1]?.method === 'POST')!
  expect(call[0]).toBe('/api/items/3/filing')
  expect(JSON.parse(String(call[1]!.body))).toEqual({ filing: 'epic', epic_key: 'DEMO-E1' })
})

it('test_unfiled_ignore_posts_ignored_and_removes_row', async () => {
  const f = vi.fn(async (_u: string, i?: RequestInit) => (i?.method === 'POST' ? json({}) : json(unfiled)))
  vi.stubGlobal('fetch', f)
  render(<Unfiled />)
  await waitFor(() => screen.getByText('Loose'))
  await userEvent.click(screen.getByRole('button', { name: 'Ignore' }))
  await waitFor(() => expect(screen.queryByText('Loose')).toBeNull())
  const call = f.mock.calls.find((c) => c[1]?.method === 'POST')!
  expect(JSON.parse(String(call[1]!.body))).toEqual({ filing: 'ignored' })
})
