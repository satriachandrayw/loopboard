import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EpicDetail from './EpicDetail'
import { clearToken } from '../token'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const t = (id: number, title: string, url: string | null = null) => ({ id, ref: `k:${id}`, title, url, waiting_on: 'agent:a', category: 'todo' })
function detail(flags: string[] = []) {
  return {
    epic: { id: 1, key: 'DEMO-E1', title: 'Epic', project_key: 'DEMO', column: 'review', stage: 'build', progress: { done: 1, total: 2 }, owner: null, waiting_on: 'human:o', waiting_since: 1, stalled: false, flags, review_owner: 'human', goal: null, next_step: null },
    tasks: { todo: [t(1, 'T-todo', 'https://x.test/1')], in_progress: [t(2, 'T-prog')], blocked: [t(3, 'T-blocked')], review: [t(4, 'T-review')], done: [t(5, 'T-done')] },
    events: [
      { id: 2, at: 200, actor: 'a', via: 'api', kind: 'newer', payload: {} },
      { id: 1, at: 100, actor: 'a', via: 'api', kind: 'older', payload: {} },
    ],
  }
}
beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('test_task_groups_in_order', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(detail())))
  render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText('T-todo'))
  const heads = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
  expect(heads.slice(0, 5)).toEqual(['Todo', 'In progress', 'Blocked', 'Review', 'Done'])
})

it('test_task_link_opens_new_tab_and_is_not_draggable', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(detail())))
  render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText('T-todo'))
  const a = screen.getByText('T-todo').closest('a')!
  expect(a.getAttribute('href')).toBe('https://x.test/1')
  expect(a.getAttribute('target')).toBe('_blank')
  expect(a.getAttribute('rel')).toBe('noreferrer')
  expect(screen.getByText('T-todo').closest('article')!.getAttribute('draggable')).not.toBe('true')
})

it('test_confirm_done_only_when_awaiting_confirmation_and_posts', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(detail())))
  const r = render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText('T-todo'))
  expect(screen.queryByRole('button', { name: 'Confirm done' })).toBeNull()
  r.unmount()
  let confirmed = false
  const f = vi.fn(async (_u: string, i?: RequestInit) => {
    if (i?.method === 'POST') { confirmed = true; return json({}) }
    return json(detail(confirmed ? [] : ['awaiting_confirmation']))
  })
  vi.stubGlobal('fetch', f)
  render(<EpicDetail epicKey="DEMO-E1" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Confirm done' }))
  await waitFor(() => expect(f.mock.calls.some((c) => c[0] === '/api/epics/DEMO-E1/confirm-done' && c[1]?.method === 'POST')).toBe(true))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Confirm done' })).toBeNull())
})

it('test_activity_newest_first', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(detail())))
  render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText(/newer/))
  const items = screen.getAllByRole('listitem').map((l) => l.textContent)
  expect(items[0]).toContain('newer')
  expect(items[1]).toContain('older')
})
