import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NeedsYou from './NeedsYou'
import Stalled from './Stalled'
import { clearToken } from '../token'
import { PROJECTS, stubApi, urls } from '../test/api'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('test_needs_you_renders_server_order_with_reasons', async () => {
  stubApi({ '/api/needs-you': [
    { kind: 'epic', id: 1, ref: 'DEMO-E1', title: 'First', waiting_on: 'human:o', waiting_since: 1, reasons: ['waiting on you', 'awaiting your approval'] },
    { kind: 'item', id: 9, ref: 'kanban:9', title: 'Second', url: 'https://x.test/9', waiting_on: 'human:o', waiting_since: 2, reasons: ['waiting on you'] },
  ] })
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
  stubApi({ '/api/stalled': [row(1, 'source', 'S1'), row(2, 'agent', 'A1'), row(3, 'human', 'H1'), row(4, 'agent', 'A2')] })
  render(<Stalled />)
  await waitFor(() => screen.getByText('A1'))
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Waiting on agent', 'Waiting on you', 'Waiting on source'])
  const agent = screen.getByText('Waiting on agent').closest('section')!
  expect(agent.textContent).toContain('A1')
  expect(agent.textContent).toContain('A2')
  expect(agent.textContent).not.toContain('H1')
})

it('test_needs_you_and_stalled_apply_the_project_chip', async () => {
  const f = stubApi({ '/api/projects': PROJECTS })
  const r = render(<NeedsYou />)
  await userEvent.click(await screen.findByRole('button', { name: 'Demo' }))
  await waitFor(() => expect(urls(f)).toContain('/api/needs-you?project=DEMO'))
  r.unmount()
  const g = stubApi({ '/api/projects': PROJECTS })
  render(<Stalled />)
  await waitFor(() => expect(urls(g)).toContain('/api/stalled?project=DEMO'))
  expect(screen.queryAllByRole('textbox')).toHaveLength(0)
})

it('test_stalled_pill_names_who_and_age', async () => {
  vi.stubGlobal('fetch', vi.fn(async (u: string) => String(u).startsWith('/api/stalled') ? json([
    { kind: 'item', id: 1, ref: 'kanban:1', title: 'A1', waiting_on: 'agent:builder', waiting_group: 'agent', waiting_since: 1, stalled_for_hours: 26.4, url: null, source: 'kanban', external_id: '1' },
    { kind: 'epic', id: 2, ref: 'DEMO-E2', title: 'H1', waiting_on: 'human:owner', waiting_group: 'human', waiting_since: 1, stalled_for_hours: 50 },
  ]) : json([])))
  render(<Stalled />)
  await screen.findByText('A1')
  expect(screen.getByText('builder · 26h').classList.contains('agent')).toBe(true)
  expect(screen.getByText('you · 2d').classList.contains('you')).toBe(true)
})

it('test_needs_you_task_row_links_to_task', async () => {
  stubApi({ '/api/needs-you': [
    { kind: 'task', id: 3, ref: 'DEMO-3', title: 'Sign off', epic_key: 'DEMO-E1', waiting_on: 'human:owner', waiting_since: 1, reasons: ['awaiting your confirmation'] },
  ] })
  render(<NeedsYou />)
  await screen.findByText('Sign off')
  const a = screen.getByText('Sign off').closest('a')!
  expect(a.getAttribute('href')).toBe('#/task/DEMO-3')
  expect(a.getAttribute('target')).toBeNull()
  const row = screen.getByText('Sign off').closest('li')!
  expect(row.querySelector('.src')!.textContent).toBe('task')
  expect(row.textContent).toContain('DEMO-3 · DEMO-E1')
  expect(screen.getByRole('link', { name: 'Open task' }).getAttribute('href')).toBe('#/task/DEMO-3')
})

it('test_stalled_task_row_links_to_task', async () => {
  stubApi({ '/api/stalled': [
    { kind: 'task', id: 3, ref: 'DEMO-3', title: 'Plan step', epic_key: null, waiting_on: 'agent:coder', waiting_group: 'agent', waiting_since: 1, stalled_for_hours: 30 },
  ] })
  render(<Stalled />)
  await screen.findByText('Plan step')
  expect(screen.getByText('Plan step').closest('a')!.getAttribute('href')).toBe('#/task/DEMO-3')
  const row = screen.getByText('Plan step').closest('li')!
  expect(row.querySelector('.src')!.textContent).toBe('task')
  expect(row.textContent).toContain('DEMO-3')
})
