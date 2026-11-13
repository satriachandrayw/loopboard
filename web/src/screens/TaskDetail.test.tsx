import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import TaskDetail from './TaskDetail'
import { clearToken } from '../token'
import { posts, stubApi, taskView } from '../test/api'

beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const link = (id: number, source: string, title: string, category: string, extra: Record<string, unknown> = {}) => ({
  id, ref: `${source}:${id}`, source, external_id: String(id), title, url: `https://x.test/${id}`, status_category: category,
  category, owner: null, waiting_on: null, last_activity_at: 1, merged_at: null, live_at: null, stalled: false, ...extra,
})

function detail(extra: Record<string, unknown> = {}) {
  return {
    ...taskView(41, 'review', {
      summary: 'Pin the runtime', description: 'Pin it in one place.', done_when: 'Checks pass on main.',
      waiting_on: 'human:owner', reporter: 'planner', flags: ['merged_not_live'],
      reason: 'Review: a linked PR is merged but not live yet',
      links_summary: { kanban: { count: 1, state: 'done' }, github: { count: 1, state: 'merged' } },
    }),
    merged_into: null, done_confirmed_at: null, created_at: 1, updated_at: 1,
    links: [link(1, 'kanban', 'Pin card', 'done'), link(2, 'github', 'Pin PR', 'review', { merged_at: 5 })],
    events: [{ id: 1, at: 1, actor: 'owner', via: 'api', kind: 'task.created', payload: {} }],
    ...extra,
  }
}
const noLinks = (extra: Record<string, unknown> = {}) =>
  detail({ status: 'todo', flags: [], reason: 'Moved by hand', links_summary: {}, links: [], ...extra })

it('test_task_detail_shows_reason_and_links', async () => {
  stubApi({ '/api/tasks/DEMO-41': detail() })
  render(<TaskDetail taskKey="DEMO-41" />)
  await screen.findByText('Pin the runtime')
  expect(screen.getByText('DEMO-41')).toBeTruthy()
  expect(screen.getByText('Review', { selector: '.status' })).toBeTruthy()
  const sub = document.querySelector('.top .s')!
  expect(sub.textContent).toBe('Epic DEMO-E1 · owner coder · waiting on you · reporter planner')
  expect(sub.querySelector('a')!.getAttribute('href')).toBe('#/epic/DEMO-E1')
  expect(sub.querySelector('.wait-human')!.textContent).toBe('you')
  expect(screen.getByText('Pin it in one place.')).toBeTruthy()
  expect(screen.getByText('Done when: Checks pass on main.')).toBeTruthy()
  expect(screen.getByText('Review: a linked PR is merged but not live yet')).toBeTruthy()
  const rows = within(screen.getByRole('table')).getAllByRole('row')
  expect(rows).toHaveLength(2)
  const pr = within(rows[1]).getByRole('link')
  expect(pr.textContent).toContain('Pin PR')
  expect(pr.getAttribute('href')).toBe('https://x.test/2')
  expect(pr.getAttribute('target')).toBe('_blank')
  expect(pr.getAttribute('rel')).toBe('noreferrer')
  expect(rows[1].textContent).toContain('merged, not live')
  expect(rows[0].textContent).toContain('done')
  expect(screen.getByText(/task\.created/)).toBeTruthy()
})

it('test_status_menu_hidden_for_linked_task', async () => {
  stubApi({ '/api/tasks/DEMO-41': detail() })
  const r = render(<TaskDetail taskKey="DEMO-41" />)
  await screen.findByText('Pin the runtime')
  expect(screen.queryByRole('button', { name: 'Move ▾' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Cancel task' })).toBeTruthy()
  r.unmount()
  let status = 'todo'
  const f = stubApi({
    '/api/tasks/DEMO-41': () => noLinks({ status }),
    'POST /api/tasks/DEMO-41/status': (_u: string, i?: RequestInit) => { status = JSON.parse(String(i!.body)).status; return {} },
  })
  render(<TaskDetail taskKey="DEMO-41" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Move ▾' }))
  expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['In progress', 'Review', 'Done'])
  await userEvent.click(screen.getByRole('menuitem', { name: 'In progress' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/tasks/DEMO-41/status', body: { status: 'in_progress' } }]))
  await waitFor(() => expect(screen.getByText('In progress', { selector: '.status' })).toBeTruthy())
})

it('test_confirm_done_button_only_when_awaiting', async () => {
  stubApi({ '/api/tasks/DEMO-41': noLinks() })
  const r = render(<TaskDetail taskKey="DEMO-41" />)
  await screen.findByText('Pin the runtime')
  expect(screen.queryByRole('button', { name: 'Confirm done' })).toBeNull()
  r.unmount()
  let confirmed = false
  const f = stubApi({
    '/api/tasks/DEMO-41': () => confirmed ? noLinks({ status: 'done' })
      : noLinks({ status: 'review', flags: ['awaiting_confirmation'], reason: 'Done by an agent; waiting for a human to confirm' }),
    'POST /api/tasks/DEMO-41/confirm-done': () => { confirmed = true; return {} },
  })
  render(<TaskDetail taskKey="DEMO-41" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Confirm done' }))
  await waitFor(() => expect(posts(f).map((p) => p.url)).toEqual(['/api/tasks/DEMO-41/confirm-done']))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Confirm done' })).toBeNull())
})

it('test_cancel_task_asks_first', async () => {
  const f = stubApi({ '/api/tasks/DEMO-41': noLinks(), 'POST /api/tasks/DEMO-41/status': {} })
  render(<TaskDetail taskKey="DEMO-41" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Cancel task' }))
  expect(posts(f)).toEqual([])
  await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
  expect(screen.queryByRole('button', { name: 'Yes, cancel DEMO-41' })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel task' }))
  await userEvent.click(screen.getByRole('button', { name: 'Yes, cancel DEMO-41' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/tasks/DEMO-41/status', body: { status: 'canceled' } }]))
})

it('test_unknown_task_says_so', async () => {
  stubApi({ '/api/tasks/DEMO-9': new Response('{}', { status: 404 }) })
  render(<TaskDetail taskKey="DEMO-9" />)
  expect((await screen.findByRole('alert')).textContent).toBe('Could not load the task.')
})
