import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Unfiled from './Unfiled'
import { clearToken } from '../token'
import { board, epicCard, json, posts, PROJECTS, stubApi, taskView, urls } from '../test/api'

beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const item = (id: number, title: string, category = 'todo', extra: Record<string, unknown> = {}) => ({
  id, source: 'kanban', external_id: `t_${id}`, title, url: `https://x.test/${id}`, owner: null, waiting_on: null,
  last_activity_at: 1, project_key: 'DEMO', status_category: category, category, merged_at: null, live_at: null, ...extra,
})
const ROWS = [
  item(1, 'Open one'),
  item(2, 'Open two', 'in_progress', { source: 'github', external_id: '#42', project_key: 'SAMPLE' }),
  item(3, 'Finished', 'done'),
  item(4, 'Shipped', 'done', { status_category: 'review', merged_at: 1, live_at: 2 }),
  item(5, 'Open three', 'review', { project_key: null }),
]
const BOARD = board({
  todo: [epicCard(1, 'todo', { title: 'Demo epic' }), epicCard(2, 'todo', { key: 'SAMPLE-E1', title: 'Sample epic', project_key: 'SAMPLE' })],
  done: [epicCard(3, 'done', { title: 'Old epic' })],
})
const lane = (epic: { key: string; title: string } | null, tasks: Record<string, unknown[]>) =>
  ({ epic: epic && { ...epic, progress: { done: 0, total: 1 } }, tasks: { todo: [], in_progress: [], review: [], done: [], ...tasks } })
const DEMO_TASKS = { project: 'DEMO', columns: ['todo', 'in_progress', 'review', 'done'], lanes: [
  lane({ key: 'DEMO-E1', title: 'Demo epic' }, { todo: [taskView(1, 'todo')], review: [taskView(3, 'review')], done: [taskView(4, 'done')] }),
  lane(null, { in_progress: [taskView(2, 'in_progress', { epic_key: null })] }),
] }
const SAMPLE_TASKS = { project: 'SAMPLE', columns: ['todo', 'in_progress', 'review', 'done'], lanes: [
  lane({ key: 'SAMPLE-E1', title: 'Sample epic' }, { todo: [taskView(8, 'todo', { key: 'SAMPLE-8', project_key: 'SAMPLE', summary: 'Sample task' })] }),
  lane(null, {}),
] }
const routes = (extra: Record<string, unknown> = {}) => ({
  '/api/unfiled': ROWS, '/api/board': BOARD, '/api/projects': PROJECTS,
  '/api/projects/DEMO/tasks': DEMO_TASKS, '/api/projects/SAMPLE/tasks': SAMPLE_TASKS, ...extra,
})
const row = (title: string) => screen.getByText(title).closest('li')!

it('test_default_shows_open_items_only_and_toggle_shows_done', async () => {
  stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  expect(screen.getByText('Open two')).toBeTruthy()
  expect(screen.getByText('Open three')).toBeTruthy()
  expect(screen.queryByText('Finished')).toBeNull()
  expect(screen.queryByText('Shipped')).toBeNull()
  const toggle = screen.getByRole('button', { name: 'Show done (2)' })
  await userEvent.click(toggle)
  expect(screen.getByText('Finished')).toBeTruthy()
  expect(screen.getByText('Shipped')).toBeTruthy()
})

it('test_row_shows_source_chip_external_id_status_and_link', async () => {
  stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open two')
  const r = row('Open two')
  expect(within(r).getByText('github').classList.contains('src')).toBe(true)
  expect(r.textContent).toContain('#42')
  expect(r.textContent).toContain('in progress')
  const link = within(r).getByRole('link', { name: /open/i })
  expect(link.getAttribute('href')).toBe('https://x.test/2')
  expect(link.getAttribute('target')).toBe('_blank')
})

it('test_project_chip_filters_unfiled', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await userEvent.click(await screen.findByRole('button', { name: 'Demo' }))
  await waitFor(() => expect(urls(f)).toContain('/api/unfiled?project=DEMO'))
})

it('test_link_to_task_menu_groups_by_epic', async () => {
  const f = stubApi(routes({ 'POST /api/items/1/link': {} }))
  const { container } = render(<Unfiled />)
  await screen.findByText('Open one')
  const r = row('Open one')
  expect(within(r).getAllByRole('button').map((b) => b.textContent)).toEqual(['Link to task ▾', 'New task from this…', 'Ignore'])
  await userEvent.click(within(r).getByRole('button', { name: 'Link to task ▾' }))
  expect([...container.querySelectorAll('.menu .mh')].map((h) => h.textContent)).toEqual(['DEMO-E1 · Demo epic', 'No epic'])
  expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['DEMO-1 · Task 1', 'DEMO-3 · Task 3', 'DEMO-2 · Task 2'])
  await userEvent.click(screen.getByRole('menuitem', { name: 'DEMO-3 · Task 3' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/items/1/link', body: { task_key: 'DEMO-3' } }]))
  await waitFor(() => expect(screen.queryByText('Open one')).toBeNull())
})

it('test_link_to_task_without_project_uses_the_chip_project', async () => {
  localStorage.setItem('loopboard.project', 'SAMPLE')
  try {
    stubApi(routes())
    render(<Unfiled />)
    await screen.findByText('Open three')
    await userEvent.click(within(row('Open three')).getByRole('button', { name: 'Link to task ▾' }))
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['SAMPLE-8 · Sample task'])
  } finally {
    localStorage.removeItem('loopboard.project')
  }
})

it('test_new_task_from_unfiled_row_links_item', async () => {
  const f = stubApi(routes({
    '/api/health': { ok: true, principal: 'owner' },
    'POST /api/projects/SAMPLE/tasks': taskView(9, 'review', { key: 'SAMPLE-9' }),
  }))
  render(<Unfiled />)
  await screen.findByText('Open two')
  await userEvent.click(within(row('Open two')).getByRole('button', { name: 'New task from this…' }))
  const dialog = screen.getByRole('dialog', { name: 'New task' })
  expect((within(dialog).getByLabelText(/^Summary/) as HTMLInputElement).value).toBe('Open two')
  expect((within(dialog).getByLabelText(/^Project/) as HTMLSelectElement).value).toBe('SAMPLE')
  await userEvent.type(within(dialog).getByLabelText(/^Description/), 'Why')
  await userEvent.type(within(dialog).getByLabelText(/^Done when/), 'Live')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create task' }))
  await waitFor(() => expect(posts(f).map((p) => p.url)).toEqual(['/api/projects/SAMPLE/tasks']))
  expect(posts(f)[0].body).toMatchObject({ summary: 'Open two', item_id: 2, description: 'Why', done_when: 'Live' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.queryByText('Open two')).toBeNull()
})

it('test_ignore_posts_ignored', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open two')
  await userEvent.click(within(row('Open two')).getByRole('button', { name: 'Ignore' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/items/2/filing', body: { filing: 'ignored' } }]))
  await waitFor(() => expect(screen.queryByText('Open two')).toBeNull())
})

it('test_bulk_ignore_three_selected_sends_three_posts_with_progress', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  await userEvent.click(screen.getByLabelText('Select all shown'))
  expect(screen.getByText('3 selected')).toBeTruthy()
  const bulk = screen.getByRole('toolbar', { name: 'Bulk actions' })
  await userEvent.click(within(bulk).getByRole('button', { name: 'Ignore' }))
  await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Filed 3/3'))
  expect(posts(f)).toEqual([1, 2, 5].map((id) => ({ url: `/api/items/${id}/filing`, body: { filing: 'ignored' } })))
  expect(screen.queryByText('Open one')).toBeNull()
})

it('test_bulk_stops_on_first_failure_and_shows_the_error', async () => {
  const f = stubApi(routes({ 'POST /api/items/2/filing': json({}, 500) }))
  render(<Unfiled />)
  await screen.findByText('Open one')
  for (const t of ['Open one', 'Open two', 'Open three'])
    await userEvent.click(screen.getByLabelText(`Select ${t}`))
  await userEvent.click(within(screen.getByRole('toolbar', { name: 'Bulk actions' })).getByRole('button', { name: 'Ignore' }))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Open two'))
  expect(posts(f).map((p) => p.url)).toEqual(['/api/items/1/filing', '/api/items/2/filing'])
  expect(screen.getByRole('status').textContent).toBe('Filed 1/3')
  expect(screen.queryByText('Open one')).toBeNull()
  expect(screen.getByText('Open two')).toBeTruthy()
})

it('test_bulk_link_to_task_posts_each_item', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  await userEvent.click(screen.getByLabelText('Select Open one'))
  await userEvent.click(screen.getByLabelText('Select Open three'))
  await userEvent.click(within(screen.getByRole('toolbar', { name: 'Bulk actions' })).getByRole('button', { name: 'Link to task ▾' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'DEMO-1 · Task 1' }))
  await waitFor(() => expect(posts(f)).toHaveLength(2))
  expect(posts(f).map((p) => p.url)).toEqual(['/api/items/1/link', '/api/items/5/link'])
  expect(posts(f).map((p) => p.body)).toEqual([{ task_key: 'DEMO-1' }, { task_key: 'DEMO-1' }])
})

it('test_no_typed_keys', async () => {
  stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  expect(screen.queryAllByRole('textbox')).toHaveLength(0)
})
