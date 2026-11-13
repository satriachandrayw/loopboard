import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import TasksBoard from './TasksBoard'
import { clearToken } from '../token'
import { mockMatchMedia, posts, PROJECTS, stubApi, taskView, tasksBoard, urls } from '../test/api'

beforeEach(() => { clearToken(); mockMatchMedia(false); localStorage.clear() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })

const E1 = { key: 'DEMO-E1', title: 'First epic', progress: { done: 1, total: 3 } }
const E2 = { key: 'DEMO-E2', title: 'Second epic', progress: { done: 0, total: 1 } }
const data = () => tasksBoard([
  { epic: E2, tasks: { todo: [taskView(4, 'todo', { epic_key: 'DEMO-E2', summary: 'Plan it' })] } },
  { epic: E1, tasks: {
    in_progress: [taskView(1, 'in_progress', { summary: 'Linked work', links_summary: { kanban: { count: 1, state: 'running' } } })],
    review: [taskView(2, 'review', { summary: 'Sign off' })],
    done: [taskView(3, 'done', { summary: 'Shipped' })] } },
  { epic: null, tasks: { review: [taskView(5, 'review', { type: 'bug', epic_key: null, summary: 'Loose bug' })] } },
])

it('test_tasks_board_needs_a_project', async () => {
  const f = stubApi({ '/api/projects': PROJECTS })
  render(<TasksBoard />)
  expect(await screen.findByText('Pick a project to see its tasks')).toBeTruthy()
  expect(urls(f).some((u) => u.includes('/tasks'))).toBe(false)
  stubApi({ '/api/projects': PROJECTS, '/api/projects/DEMO/tasks': data() })
  await userEvent.click(await screen.findByRole('button', { name: 'Demo' }))
  expect(await screen.findByText('Linked work')).toBeTruthy()
})

it('test_lanes_render_in_api_order_with_no_epic_last', async () => {
  localStorage.setItem('loopboard.project', 'DEMO')
  stubApi({ '/api/projects': PROJECTS, '/api/projects/DEMO/tasks': data() })
  const { container } = render(<TasksBoard />)
  await screen.findByText('Linked work')
  const heads = [...container.querySelectorAll('.laneh')].map((h) => h.textContent)
  expect(heads[0]).toContain('DEMO-E2')
  expect(heads[0]).toContain('Second epic')
  expect(heads[1]).toContain('1/3')
  expect(heads[2]).toContain('No epic')
  // column headers once, at the top
  expect([...container.querySelectorAll('.colhead div')].map((d) => d.textContent)).toEqual(['Todo', 'In progress', 'Review', 'Done'])
  const lane = container.querySelectorAll('.lane')[1]
  expect(within(lane.querySelector('[data-column="review"]') as HTMLElement).getByText('Sign off')).toBeTruthy()
})

it('test_lane_folds_and_remembers', async () => {
  localStorage.setItem('loopboard.project', 'DEMO')
  stubApi({ '/api/projects': PROJECTS, '/api/projects/DEMO/tasks': data() })
  const r = render(<TasksBoard />)
  await screen.findByText('Linked work')
  const fold = screen.getByRole('button', { name: /DEMO-E1/ })
  expect(fold.getAttribute('aria-expanded')).toBe('true')
  await userEvent.click(fold)
  expect(screen.queryByText('Linked work')).toBeNull()
  expect(JSON.parse(localStorage.getItem('loopboard.lanes.DEMO')!)).toEqual(['DEMO-E1'])
  r.unmount()
  render(<TasksBoard />)
  await screen.findByText('Plan it')
  expect(screen.queryByText('Linked work')).toBeNull()
  expect(screen.getByRole('button', { name: /DEMO-E1/ }).getAttribute('aria-expanded')).toBe('false')
})

it('test_only_unlinked_cards_are_draggable', async () => {
  localStorage.setItem('loopboard.project', 'DEMO')
  stubApi({ '/api/projects': PROJECTS, '/api/projects/DEMO/tasks': data() })
  render(<TasksBoard />)
  const linked = (await screen.findByText('Linked work')).closest('article')!
  expect(linked.getAttribute('draggable')).toBe('false')
  expect(screen.getByText('Sign off').closest('article')!.getAttribute('draggable')).toBe('true')
})

it('test_drop_posts_status_and_reloads', async () => {
  localStorage.setItem('loopboard.project', 'DEMO')
  const f = stubApi({ '/api/projects': PROJECTS, '/api/projects/DEMO/tasks': data(), 'POST /api/tasks/DEMO-2/status': taskView(2, 'done') })
  const { container } = render(<TasksBoard />)
  const card = (await screen.findByText('Sign off')).closest('article')!
  const store: Record<string, string> = {}
  const dataTransfer = { setData: (k: string, v: string) => { store[k] = v }, getData: (k: string) => store[k] ?? '' }
  fireEvent.dragStart(card, { dataTransfer })
  const target = container.querySelectorAll('.lane')[1].querySelector('[data-column="done"]')!
  fireEvent.dragOver(target, { dataTransfer })
  fireEvent.drop(target, { dataTransfer })
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/tasks/DEMO-2/status', body: { status: 'done' } }]))
  await waitFor(() => expect(urls(f).filter((u) => u === '/api/projects/DEMO/tasks')).toHaveLength(2))
  // a linked card is never posted
  const linked = screen.getByText('Linked work').closest('article')!
  fireEvent.dragStart(linked, { dataTransfer: { setData: () => {}, getData: () => '' } })
  fireEvent.drop(target, { dataTransfer: { setData: () => {}, getData: () => '' } })
  expect(posts(f)).toHaveLength(1)
})

it('test_phone_shows_one_column_with_epic_headings', async () => {
  localStorage.setItem('loopboard.project', 'DEMO')
  mockMatchMedia(true)
  stubApi({ '/api/projects': PROJECTS, '/api/projects/DEMO/tasks': data() })
  render(<TasksBoard />)
  const tabs = await screen.findAllByRole('tab')
  expect(tabs.map((t) => t.textContent)).toEqual(['Todo 1', 'In progress 1', 'Review 2', 'Done 1'])
  expect(screen.getByText('Plan it')).toBeTruthy()
  expect(screen.queryByText('Sign off')).toBeNull()
  await userEvent.click(tabs[2])
  expect(screen.getByText('Sign off')).toBeTruthy()
  expect(screen.getByText('Loose bug')).toBeTruthy()
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toContain('DEMO-E1 · First epic')
})
