import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Board from './Board'
import { clearToken } from '../token'
import { board, epicCard as card, json, mockMatchMedia, PROJECTS, stubApi, urls } from '../test/api'

beforeEach(() => { clearToken(); mockMatchMedia(false) })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })

const oneCard = () => board({ todo: [card(1, 'todo')] })

it('test_five_columns_in_order_with_descriptions', async () => {
  stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  render(<Board />)
  await waitFor(() => expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(5))
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(
    ['Backlog', 'Todo', 'In progress', 'Review', 'Done'].map((l) => expect.stringContaining(l)),
  )
  for (const d of ['Parked ideas. Nothing starts here.', 'You said go. Spec and plan get written and approved.',
    'Agents building. Moves by itself.', 'Handed over to review, merge and deploy.', 'Live, not just merged. Hides after 7 days.'])
    expect(screen.getByText(d)).toBeTruthy()
})

it('test_review_limit_shown_and_coloured_only_when_over', async () => {
  stubApi({ '/api/board': board({ todo: [card(1, 'todo')] }, 3) })
  const r = render(<Board />)
  const limit = await screen.findByText('3 / 3 limit')
  expect(limit.classList.contains('warn')).toBe(false)
  r.unmount()
  stubApi({ '/api/board': board({ todo: [card(1, 'todo')] }, 4) })
  render(<Board />)
  expect((await screen.findByText('4 / 3 limit')).classList.contains('warn')).toBe(true)
})

it('test_project_chips_render_with_all_projects_default', async () => {
  stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  render(<Board />)
  const all = await screen.findByRole('button', { name: 'All projects' })
  expect(all.getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: 'Demo' }).getAttribute('aria-pressed')).toBe('false')
  expect(screen.getByRole('button', { name: 'Sample' })).toBeTruthy()
})

it('test_clicking_a_chip_requests_project_and_persists_across_reloads', async () => {
  const f = stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  const r = render(<Board />)
  await userEvent.click(await screen.findByRole('button', { name: 'Sample' }))
  await waitFor(() => expect(urls(f)).toContain('/api/board?project=SAMPLE'))
  expect(screen.getByRole('button', { name: 'Sample' }).getAttribute('aria-pressed')).toBe('true')
  r.unmount()
  const g = stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  render(<Board />)
  await waitFor(() => expect(urls(g)).toContain('/api/board?project=SAMPLE'))
  expect(urls(g).filter((u) => u.startsWith('/api/board'))).toEqual(['/api/board?project=SAMPLE'])
  await userEvent.click(await screen.findByRole('button', { name: 'All projects' }))
  await waitFor(() => expect(urls(g)).toContain('/api/board'))
})

it('test_unknown_stored_project_falls_back_to_all', async () => {
  localStorage.setItem('loopboard.project', 'GONE')
  const f = stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  render(<Board />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'All projects' }).getAttribute('aria-pressed')).toBe('true'))
  await waitFor(() => expect(urls(f)).toContain('/api/board'))
})

it('test_no_free_text_project_input', async () => {
  stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  render(<Board />)
  await screen.findByRole('button', { name: 'Demo' })
  expect(screen.queryByRole('textbox', { name: /project/i })).toBeNull()
  expect(screen.queryAllByRole('textbox')).toHaveLength(0)
})

it('test_waiting_on_dropdown_requests_param', async () => {
  const f = stubApi({ '/api/board': oneCard() })
  render(<Board />)
  await screen.findByText('Epic 1')
  await userEvent.selectOptions(screen.getByLabelText('Waiting on'), 'human')
  await waitFor(() => expect(urls(f)).toContain('/api/board?waiting_on=human'))
})

it('test_empty_state_with_open_unfiled_count', async () => {
  const u = (id: number, category: string, live_at: number | null = null) => ({
    id, source: 'kanban', external_id: String(id), title: `I${id}`, url: null, owner: null, waiting_on: null,
    last_activity_at: 1, project_key: null, status_category: category, category, merged_at: null, live_at,
  })
  stubApi({ '/api/board': board(), '/api/projects': PROJECTS,
    '/api/unfiled': [u(1, 'todo'), u(2, 'in_progress'), u(3, 'done'), u(4, 'review', 5)] })
  render(<Board />)
  await screen.findByText('No epics yet')
  expect(await screen.findByText(/2 open unfiled items/)).toBeTruthy()
  expect(screen.getByRole('link', { name: 'File them →' }).getAttribute('href')).toBe('#/unfiled')
  const panel = screen.getByText('No epics yet').closest('section')!
  expect(within(panel).getByRole('button', { name: '+ New epic' })).toBeTruthy()
  expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0)
})

it('test_new_epic_button_opens_form', async () => {
  stubApi({ '/api/board': oneCard(), '/api/projects': PROJECTS })
  render(<Board />)
  await screen.findByText('Epic 1')
  await userEvent.click(screen.getByRole('button', { name: '+ New epic' }))
  expect(screen.getByRole('dialog', { name: 'New epic' })).toBeTruthy()
})

it('test_narrow_screen_shows_one_column_with_tabs', async () => {
  mockMatchMedia(true)
  stubApi({ '/api/board': board({ backlog: [card(1, 'backlog')], todo: [card(2, 'todo')] }) })
  render(<Board />)
  await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(5))
  expect(screen.getAllByRole('tab')[0].textContent).toBe('Backlog 1')
  expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1)
  expect(screen.getByText('Epic 1')).toBeTruthy()
  await userEvent.click(screen.getAllByRole('tab')[1])
  expect(screen.getByText('Epic 2')).toBeTruthy()
  expect(screen.queryByText('Epic 1')).toBeNull()
})

it('test_move_menu_offers_todo_not_in_progress_and_patches', async () => {
  const f = stubApi({ '/api/board': board({ backlog: [card(1, 'backlog')] }), 'PATCH /api/epics/DEMO-E1': {} })
  render(<Board />)
  await screen.findByText('Epic 1')
  await userEvent.click(screen.getByRole('button', { name: 'Move' }))
  expect(screen.queryByRole('menuitem', { name: 'In progress' })).toBeNull()
  expect(screen.getByRole('menuitem', { name: 'Canceled' })).toBeTruthy()
  await userEvent.click(screen.getByRole('menuitem', { name: 'Todo' }))
  await waitFor(() => {
    const c = f.mock.calls.find((x) => x[1]?.method === 'PATCH')!
    expect(c[0]).toBe('/api/epics/DEMO-E1')
    expect(JSON.parse(c[1]!.body as string)).toEqual({ manual_column: 'todo' })
  })
  expect(window.location.hash).toBe('')
})

it('test_clicking_the_card_opens_epic_detail', async () => {
  stubApi({ '/api/board': oneCard() })
  const { container } = render(<Board />)
  await screen.findByText('Epic 1')
  await userEvent.click(container.querySelector('.card .w')!)
  expect(window.location.hash).toBe('#/epic/DEMO-E1')
})

it('drag from backlog to todo patches', async () => {
  const f = stubApi({ '/api/board': board({ backlog: [card(1, 'backlog')] }), 'PATCH /api/epics/DEMO-E1': {} })
  const { container } = render(<Board />)
  await screen.findByText('Epic 1')
  const dt = { data: {} as Record<string, string>, setData(k: string, v: string) { this.data[k] = v }, getData(k: string) { return this.data[k] }, effectAllowed: '' }
  fireEvent.dragStart(container.querySelector('.card')!, { dataTransfer: dt })
  fireEvent.drop(container.querySelector('[data-column="in_progress"]')!, { dataTransfer: dt })
  expect(f.mock.calls.some((x) => x[1]?.method === 'PATCH')).toBe(false)
  fireEvent.drop(container.querySelector('[data-column="todo"]')!, { dataTransfer: dt })
  await waitFor(() => expect(f.mock.calls.some((x) => x[1]?.method === 'PATCH')).toBe(true))
})

it('test_401_shows_token_prompt_and_retries_after_save', async () => {
  const f = vi.fn(async (u: string, init?: RequestInit) => {
    const auth = new Headers(init?.headers).get('Authorization')
    if (auth !== 'Bearer lb_good') return json({}, 401)
    return String(u).startsWith('/api/board') ? json(oneCard()) : json([])
  })
  vi.stubGlobal('fetch', f)
  render(<Board />)
  await waitFor(() => screen.getByLabelText('Token'))
  await userEvent.type(screen.getByLabelText('Token'), 'lb_good')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => screen.getByText('Epic 1'))
  expect(localStorage.getItem('loopboard.token')).toBe('lb_good')
})

it('test_stale_board_response_is_ignored', async () => {
  let releaseFirst: (r: Response) => void = () => {}
  const f = vi.fn((u: string) => {
    if (!String(u).startsWith('/api/board')) return Promise.resolve(json([]))
    if (!u.includes('waiting_on')) return new Promise<Response>((res) => { releaseFirst = res })
    return Promise.resolve(json(board({ todo: [card(2, 'todo')] })))
  })
  vi.stubGlobal('fetch', f)
  render(<Board />)
  await userEvent.selectOptions(screen.getByLabelText('Waiting on'), 'human')
  await waitFor(() => screen.getByText('Epic 2'))
  releaseFirst(json(board({ todo: [card(1, 'todo')] })))
  await new Promise((r) => setTimeout(r, 20))
  expect(screen.getByText('Epic 2')).toBeTruthy()
  expect(screen.queryByText('Epic 1')).toBeNull()
})
