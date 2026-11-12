import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { clearToken } from './token'
import { board, epicCard, mockMatchMedia, PROJECTS, stubApi, urls } from './test/api'

const unfiled = (id: number, category: string) => ({
  id, source: 'kanban', external_id: String(id), title: `I${id}`, url: null, owner: null, waiting_on: null,
  last_activity_at: 1, project_key: null, status_category: category, category, merged_at: null, live_at: null,
})
const routes = {
  '/api/board': board({ todo: [epicCard(1, 'todo')] }),
  '/api/projects': PROJECTS,
  '/api/needs-you': [{ kind: 'epic', id: 1, ref: 'DEMO-E1', title: 'x', waiting_on: 'human:o', waiting_since: 1, reasons: [] },
    { kind: 'epic', id: 2, ref: 'DEMO-E2', title: 'y', waiting_on: 'human:o', waiting_since: 1, reasons: [] }],
  '/api/unfiled': [unfiled(1, 'todo'), unfiled(2, 'done'), unfiled(3, 'review')],
}

beforeEach(() => { clearToken(); mockMatchMedia(false) })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })

it('test_malformed_epic_hash_falls_back_to_board', async () => {
  stubApi(routes)
  window.location.hash = '#/epic/%E0%A4%A'
  render(<App />)
  await waitFor(() => expect(screen.getByText('Epic 1')).toBeTruthy())
})

it('test_header_nav_with_badges_from_read_apis', async () => {
  stubApi(routes)
  render(<App />)
  expect(screen.getByText('◎ loopboard')).toBeTruthy()
  const nav = screen.getByRole('navigation', { name: 'Main' })
  const links = within(nav).getAllByRole('link')
  expect(links.map((l) => l.getAttribute('href'))).toEqual(['#/needs-you', '#/stalled', '#/board', '#/unfiled'])
  await waitFor(() => expect(within(links[0]).getByText('2')).toBeTruthy())
  // Unfiled counts open items only.
  await waitFor(() => expect(within(links[3]).getByText('2')).toBeTruthy())
  expect(links[2].getAttribute('aria-current')).toBe('page')
  expect(screen.queryByRole('navigation', { name: 'Tabs' })).toBeNull()
})

it('test_badges_follow_the_project_chip', async () => {
  localStorage.setItem('loopboard.project', 'DEMO')
  const f = stubApi(routes)
  render(<App />)
  await waitFor(() => expect(urls(f)).toContain('/api/needs-you?project=DEMO'))
  expect(urls(f)).toContain('/api/unfiled?project=DEMO')
})

it('test_phone_layout_renders_bottom_tabs_at_375px', async () => {
  mockMatchMedia(true)
  vi.stubGlobal('innerWidth', 375)
  stubApi(routes)
  render(<App />)
  const tabs = screen.getByRole('navigation', { name: 'Tabs' })
  expect(within(tabs).getAllByRole('link').map((l) => l.textContent)).toEqual(
    ['🙋Needs you2', '⏳Stalled', '▦Board', '📥Unfiled2'].map((t) => expect.stringContaining(t.replace(/\d$/, ''))),
  )
  await waitFor(() => expect(within(tabs).getAllByRole('link')[0].textContent).toBe('🙋Needs you2'))
  expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull()
})

it('test_no_free_text_project_input_on_any_screen', async () => {
  stubApi(routes)
  for (const h of ['#/board', '#/needs-you', '#/stalled', '#/unfiled']) {
    window.location.hash = h
    const r = render(<App />)
    await screen.findByRole('button', { name: 'Demo' })
    expect(screen.queryByRole('textbox', { name: /project/i })).toBeNull()
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
    r.unmount()
  }
})
