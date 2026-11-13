import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Unfiled from './Unfiled'
import { clearToken } from '../token'
import { board, epicCard, json, posts, PROJECTS, stubApi, urls } from '../test/api'

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
const routes = (extra: Record<string, unknown> = {}) => ({
  '/api/unfiled': ROWS, '/api/board': BOARD, '/api/projects': PROJECTS, ...extra,
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

it('test_file_to_epic_lists_open_epics_of_the_item_project_and_posts', async () => {
  const f = stubApi(routes({ 'POST /api/items/1/filing': {} }))
  render(<Unfiled />)
  await screen.findByText('Open one')
  await userEvent.click(within(row('Open one')).getByRole('button', { name: 'File to epic ▾' }))
  const items = screen.getAllByRole('menuitem').map((m) => m.textContent)
  expect(items).toEqual(['DEMO-E1 · Demo epic', '+ New epic…'])
  await userEvent.click(screen.getByRole('menuitem', { name: 'DEMO-E1 · Demo epic' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/items/1/filing', body: { filing: 'epic', epic_key: 'DEMO-E1' } }]))
  await waitFor(() => expect(screen.queryByText('Open one')).toBeNull())
})

it('test_file_to_epic_without_project_lists_all_open_epics', async () => {
  stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open three')
  await userEvent.click(within(row('Open three')).getByRole('button', { name: 'File to epic ▾' }))
  expect(screen.getAllByRole('menuitem').map((m) => m.textContent))
    .toEqual(['DEMO-E1 · Demo epic', 'SAMPLE-E1 · Sample epic', '+ New epic…'])
})

it('test_new_epic_from_row_prefills_creates_then_files', async () => {
  const f = stubApi(routes({
    '/api/health': { ok: true, principal: 'owner' },
    'POST /api/projects/SAMPLE/epics': { id: 9, key: 'SAMPLE-E2', title: 'Open two' },
    'POST /api/items/2/filing': {},
  }))
  render(<Unfiled />)
  await screen.findByText('Open two')
  await userEvent.click(within(row('Open two')).getByRole('button', { name: 'File to epic ▾' }))
  await userEvent.click(screen.getByRole('menuitem', { name: '+ New epic…' }))
  const dialog = screen.getByRole('dialog', { name: 'New epic' })
  expect((within(dialog).getByLabelText('Title') as HTMLInputElement).value).toBe('Open two')
  expect((within(dialog).getByLabelText('Project') as HTMLSelectElement).value).toBe('SAMPLE')
  await userEvent.type(within(dialog).getByLabelText('Description'), 'Why')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  await waitFor(() => expect(posts(f).map((p) => p.url)).toEqual(['/api/projects/SAMPLE/epics', '/api/items/2/filing']))
  expect(posts(f)[0].body.goal).toBe('Why')
  expect(posts(f)[1].body).toEqual({ filing: 'epic', epic_key: 'SAMPLE-E2' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('test_standalone_uses_the_item_project_and_ignore_posts_ignored', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  await userEvent.click(within(row('Open one')).getByRole('button', { name: 'Standalone' }))
  await waitFor(() => expect(posts(f)).toHaveLength(1))
  expect(posts(f)[0]).toEqual({ url: '/api/items/1/filing', body: { filing: 'standalone', project_key: 'DEMO' } })
  await userEvent.click(within(row('Open two')).getByRole('button', { name: 'Ignore' }))
  await waitFor(() => expect(posts(f)).toHaveLength(2))
  expect(posts(f)[1]).toEqual({ url: '/api/items/2/filing', body: { filing: 'ignored' } })
  await waitFor(() => expect(screen.queryByText('Open two')).toBeNull())
})

it('test_standalone_without_project_offers_a_project_menu', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open three')
  await userEvent.click(within(row('Open three')).getByRole('button', { name: 'Standalone ▾' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Sample' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/items/5/filing', body: { filing: 'standalone', project_key: 'SAMPLE' } }]))
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

it('test_bulk_file_to_epic_posts_each_item', async () => {
  const f = stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  await userEvent.click(screen.getByLabelText('Select Open one'))
  await userEvent.click(screen.getByLabelText('Select Open three'))
  await userEvent.click(within(screen.getByRole('toolbar', { name: 'Bulk actions' })).getByRole('button', { name: 'File to epic ▾' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'SAMPLE-E1 · Sample epic' }))
  await waitFor(() => expect(posts(f)).toHaveLength(2))
  expect(posts(f).map((p) => p.body)).toEqual([1, 2].map(() => ({ filing: 'epic', epic_key: 'SAMPLE-E1' })))
})

it('test_no_typed_keys', async () => {
  stubApi(routes())
  render(<Unfiled />)
  await screen.findByText('Open one')
  expect(screen.queryAllByRole('textbox')).toHaveLength(0)
})

it('test_new_epic_from_row_without_description_files_nothing', async () => {
  const f = stubApi(routes({
    '/api/health': { ok: true, principal: 'owner' },
    'POST /api/projects/SAMPLE/epics': { id: 9, key: 'SAMPLE-E2', title: 'Open two' },
    'POST /api/items/2/filing': {},
  }))
  render(<Unfiled />)
  await screen.findByText('Open two')
  await userEvent.click(within(row('Open two')).getByRole('button', { name: 'File to epic ▾' }))
  await userEvent.click(screen.getByRole('menuitem', { name: '+ New epic…' }))
  const dialog = screen.getByRole('dialog', { name: 'New epic' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  expect(within(dialog).getByRole('alert').textContent).toBe('Add a description: what this epic is for.')
  expect(posts(f)).toEqual([])
  expect(screen.getByRole('dialog', { name: 'New epic' })).toBeTruthy()
})
