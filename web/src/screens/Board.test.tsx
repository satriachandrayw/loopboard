import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Board from './Board'
import { clearToken } from '../token'

const COLS = [['backlog', 'Backlog'], ['todo', 'Todo'], ['in_progress', 'In progress'], ['review', 'Review'], ['done', 'Done']]
const card = (id: number, column: string) => ({
  id, key: `DEMO-E${id}`, title: `Epic ${id}`, project_key: 'DEMO', column, stage: 'build',
  progress: { done: 0, total: 1 }, owner: null, waiting_on: 'agent:a', waiting_since: 1, stalled: false, flags: [], review_owner: null,
})
function board(reviewCount = 0, cards: Record<string, unknown[]> = {}) {
  return {
    columns: COLS.map(([c, label]) => ({
      column: c, label, count: c === 'review' ? reviewCount : (cards[c]?.length ?? 0),
      warn: c === 'review' && reviewCount >= 4, cards: cards[c] ?? [],
    })),
  }
}
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
function mm(narrow: boolean) {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: narrow, media: q, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false,
  }))
}
beforeEach(() => { clearToken(); mm(false) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('test_five_columns_in_order', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(board())))
  render(<Board />)
  await waitFor(() => expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(5))
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(
    ['Backlog', 'Todo', 'In progress', 'Review', 'Done'].map((l) => expect.stringContaining(l)),
  )
})

it('test_review_warning_at_four_not_three', async () => {
  const f = vi.fn(async () => json(board(3)))
  vi.stubGlobal('fetch', f)
  const r = render(<Board />)
  await waitFor(() => screen.getByText('Backlog'))
  expect(screen.queryByText('Review is backing up')).toBeNull()
  r.unmount()
  vi.stubGlobal('fetch', vi.fn(async () => json(board(4))))
  render(<Board />)
  await waitFor(() => expect(screen.getByText('Review is backing up')).toBeTruthy())
})

it('test_project_filter_requests_project_param', async () => {
  const f = vi.fn(async (_u: string, _i?: RequestInit) => json(board()))
  vi.stubGlobal('fetch', f)
  render(<Board />)
  await waitFor(() => screen.getByText('Backlog'))
  await userEvent.type(screen.getByLabelText('Project'), 'DEMO')
  await waitFor(() => expect(f.mock.calls.some((c) => String(c[0]).includes('project=DEMO'))).toBe(true))
  await userEvent.selectOptions(screen.getByLabelText('Waiting on'), 'human')
  await waitFor(() => expect(f.mock.calls.some((c) => String(c[0]).includes('waiting_on=human'))).toBe(true))
})

it('test_narrow_screen_shows_one_column_with_tabs', async () => {
  mm(true)
  vi.stubGlobal('fetch', vi.fn(async () => json(board(0, { backlog: [card(1, 'backlog')], todo: [card(2, 'todo')] }))))
  render(<Board />)
  await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(5))
  expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1)
  expect(screen.getByText('Epic 1')).toBeTruthy()
  await userEvent.click(screen.getAllByRole('tab')[1])
  expect(screen.getByText('Epic 2')).toBeTruthy()
  expect(screen.queryByText('Epic 1')).toBeNull()
})

it('test_move_menu_offers_todo_not_in_progress_and_patches', async () => {
  const f = vi.fn(async (_u: string, init?: RequestInit) =>
    init?.method === 'PATCH' ? json({}) : json(board(0, { backlog: [card(1, 'backlog')] })))
  vi.stubGlobal('fetch', f)
  render(<Board />)
  await waitFor(() => screen.getByText('Epic 1'))
  await userEvent.click(screen.getByRole('button', { name: 'Move' }))
  expect(screen.queryByRole('menuitem', { name: 'In progress' })).toBeNull()
  expect(screen.getByRole('menuitem', { name: 'Canceled' })).toBeTruthy()
  await userEvent.click(screen.getByRole('menuitem', { name: 'Todo' }))
  await waitFor(() => {
    const c = f.mock.calls.find((x) => x[1]?.method === 'PATCH')!
    expect(c[0]).toBe('/api/epics/DEMO-E1')
    expect(JSON.parse(c[1]!.body as string)).toEqual({ manual_column: 'todo' })
  })
})

it('drag from backlog to todo patches', async () => {
  const f = vi.fn(async (_u: string, init?: RequestInit) =>
    init?.method === 'PATCH' ? json({}) : json(board(0, { backlog: [card(1, 'backlog')] })))
  vi.stubGlobal('fetch', f)
  const { container } = render(<Board />)
  await waitFor(() => screen.getByText('Epic 1'))
  const dt = { data: {} as Record<string, string>, setData(k: string, v: string) { this.data[k] = v }, getData(k: string) { return this.data[k] }, effectAllowed: '' }
  fireEvent.dragStart(container.querySelector('.card')!, { dataTransfer: dt })
  fireEvent.drop(container.querySelector('[data-column="in_progress"]')!, { dataTransfer: dt })
  expect(f.mock.calls.some((x) => x[1]?.method === 'PATCH')).toBe(false)
  fireEvent.drop(container.querySelector('[data-column="todo"]')!, { dataTransfer: dt })
  await waitFor(() => expect(f.mock.calls.some((x) => x[1]?.method === 'PATCH')).toBe(true))
})

it('test_401_shows_token_prompt_and_retries_after_save', async () => {
  const f = vi.fn(async (_u: string, init?: RequestInit) => {
    const auth = new Headers(init?.headers).get('Authorization')
    return auth === 'Bearer lb_good' ? json(board()) : json({}, 401)
  })
  vi.stubGlobal('fetch', f)
  render(<Board />)
  await waitFor(() => screen.getByLabelText('Token'))
  await userEvent.type(screen.getByLabelText('Token'), 'lb_good')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => screen.getByText('Backlog'))
  expect(localStorage.getItem('loopboard.token')).toBe('lb_good')
})
