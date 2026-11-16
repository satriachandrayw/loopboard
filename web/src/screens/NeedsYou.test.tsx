import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NeedsYou from './NeedsYou'
import { clearToken } from '../token'
import { mockWidth, needsRow, posts, stubApi, taskView } from '../test/api'

beforeEach(() => { clearToken(); mockWidth(390) })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

const release = needsRow('release:DEMO', 'release', {
  kind: 'release', id: 1, title: 'Demo: 2 changes merged, not live', epic_key: null, question: 'Release Demo to its live branch?',
  reply_code: 'release demo', context: 'first, second', reasons: ['merged, not live'], auto: true,
  items: [
    { ref: 'github:owner/sample#1', title: 'first', url: 'https://example.test/pr/1', project_key: 'DEMO' },
    { ref: 'github:owner/sample#2', title: 'second', url: 'https://example.test/pr/2', project_key: 'DEMO' },
  ],
})
const ROWS = [
  needsRow('DEMO-1', 'decide'),
  needsRow('DEMO-2', 'decide', { question: 'No question recorded yet.', missing_question: true, auto: true, reply_code: 'DEMO-2?' }),
  needsRow('DEMO-3', 'review'),
  release,
  needsRow('DEMO-4', 'confirm', { question: 'The agent says this is done. Is it?', reply_code: null,
    answer_how: 'Press Confirm done, or tell your agent what is missing.' }),
  needsRow('DEMO-5', 'later'),
  needsRow('DEMO-6', 'later'),
]

it('test_groups_in_order_with_subline', async () => {
  stubApi({ '/api/needs-you': ROWS })
  render(<NeedsYou />)
  await screen.findByText('Title DEMO-1')
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(
    ['Decide 2', 'Review 1', 'Release 1', 'Confirm 1', 'Later 2'])
  expect(document.querySelector('.top .s')!.textContent).toBe('5 to answer now · 2 later · oldest first in each group')
  const decide = screen.getAllByRole('listitem').slice(0, 2).map((li) => li.textContent)
  expect(decide[0]).toContain('Title DEMO-1')
  expect(decide[1]).toContain('Title DEMO-2')
})

it('test_row_shows_kind_question_context_and_how', async () => {
  stubApi({ '/api/needs-you': ROWS })
  render(<NeedsYou />)
  const li = (await screen.findByText('Title DEMO-1')).closest('li')!
  expect(li.querySelector('.kind')!.textContent).toBe('Decide')
  expect(li.querySelector('.kind')!.classList.contains('k-decide')).toBe(true)
  expect(li.querySelector('.q')!.textContent).toBe('Question DEMO-1?')
  expect(li.querySelector('.ctx')!.textContent).toBe('Context DEMO-1.')
  expect(li.querySelector('.how')!.textContent).toContain('Reply to your agent:')
  expect(li.querySelector('.code')!.textContent).toBe('go DEMO-1')
  expect(li.querySelector('.meta')!.textContent).toBe('task DEMO-1 · DEMO-E1')
  const more = within(li).getByText('Context and details ›')
  expect(more.getAttribute('href')).toBe('#/task/DEMO-1')
  expect(screen.getByText('Title DEMO-1').closest('a')!.getAttribute('href')).toBe('#/task/DEMO-1')
  expect(within(li).queryByText('No question recorded')).toBeNull()
  const missing = screen.getByText('Title DEMO-2').closest('li')!
  expect(within(missing).getByText('No question recorded')).toBeTruthy()
})

it('test_copy_copies_reply_code', async () => {
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  stubApi({ '/api/needs-you': ROWS })
  render(<NeedsYou />)
  const li = (await screen.findByText('Title DEMO-1')).closest('li')!
  const btn = within(li).getByRole('button', { name: 'Copy go DEMO-1' })
  expect(btn.textContent).toBe('Copy')
  vi.useFakeTimers({ shouldAdvanceTime: true })
  fireEvent.click(btn)
  await waitFor(() => expect(btn.textContent).toBe('Copied'))
  expect(writeText).toHaveBeenCalledWith('go DEMO-1')
  vi.advanceTimersByTime(2100)
  await waitFor(() => expect(btn.textContent).toBe('Copy'))
})

it('test_later_collapsed_with_count', async () => {
  stubApi({ '/api/needs-you': ROWS })
  render(<NeedsYou />)
  await screen.findByText('Title DEMO-1')
  expect(screen.queryByText('Title DEMO-5')).toBeNull()
  const toggle = screen.getByRole('button', { name: /DEMO-5 Title DEMO-5 · DEMO-6 Title DEMO-6/ })
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  await userEvent.click(toggle)
  expect(screen.getByText('Title DEMO-5')).toBeTruthy()
})

it('test_only_later_rows', async () => {
  stubApi({ '/api/needs-you': ROWS.slice(5) })
  render(<NeedsYou />)
  await screen.findByText('Later')
  expect(document.querySelector('.top .s')!.textContent).toBe('0 to answer now · 2 later · oldest first in each group')
  expect(screen.queryByText('Title DEMO-5')).toBeNull()
})

it('test_empty_keeps_current_empty_state', async () => {
  stubApi({ '/api/needs-you': [] })
  render(<NeedsYou />)
  await screen.findByText('Nothing needs you right now.')
  expect(screen.queryAllByRole('heading', { level: 2 })).toHaveLength(0)
})

it('test_release_row_expands_to_items', async () => {
  stubApi({ '/api/needs-you': ROWS })
  render(<NeedsYou />)
  const li = (await screen.findByText('Demo: 2 changes merged, not live')).closest('li')!
  expect(li.querySelector('.kind')!.textContent).toBe('Release')
  expect(li.querySelector('.code')!.textContent).toBe('release demo')
  expect(within(li).queryByRole('link', { name: 'first' })).toBeNull()
  await userEvent.click(within(li).getByRole('button', { name: 'Context and details ›' }))
  const a = within(li).getByRole('link', { name: 'first' })
  expect(a.getAttribute('href')).toBe('https://example.test/pr/1')
  expect(a.getAttribute('target')).toBe('_blank')
  expect(a.getAttribute('rel')).toBe('noreferrer')
  expect(within(li).getByRole('link', { name: 'second' })).toBeTruthy()
})

it('test_confirm_row_calls_confirm_done', async () => {
  let confirmed = false
  const f = stubApi({
    '/api/needs-you': () => (confirmed ? ROWS.filter((r) => r.ref !== 'DEMO-4') : ROWS),
    'POST /api/tasks/DEMO-4/confirm-done': () => { confirmed = true; return {} },
  })
  render(<NeedsYou />)
  const li = (await screen.findByText('Title DEMO-4')).closest('li')!
  expect(li.querySelector('.code')).toBeNull()
  await userEvent.click(within(li).getByRole('button', { name: 'Confirm done' }))
  await waitFor(() => expect(posts(f)).toEqual([{ url: '/api/tasks/DEMO-4/confirm-done', body: {} }]))
  await waitFor(() => expect(screen.queryByText('Title DEMO-4')).toBeNull())
})

it('test_desktop_split_shows_selected_row_detail', async () => {
  mockWidth(1280)
  stubApi({
    '/api/needs-you': ROWS,
    '/api/tasks/DEMO-3': {
      ...taskView(3, 'review', { summary: 'Title DEMO-3', description: 'Full context.', waiting_on: 'human:owner' }),
      merged_into: null, done_confirmed_at: null, created_at: 1, updated_at: 1, links: [], events: [],
      epic_next_step: 'Write the plan.',
      ask: { ask_kind: 'review', question: 'Question DEMO-3?', answer_how: 'Reply to your agent:', reply_code: 'go DEMO-3',
        auto: false, missing_question: false },
    },
  })
  render(<NeedsYou selected="DEMO-3" />)
  const pane = await waitFor(() => document.querySelector('.split .r')!)
  await within(pane as HTMLElement).findByText('Full context.')
  expect(within(pane as HTMLElement).getByText('Your answer')).toBeTruthy()
  expect(within(pane as HTMLElement).getByText('Write the plan.')).toBeTruthy()
  const sel = document.querySelector('.split .l .card.sel')!
  expect(sel.textContent).toContain('Title DEMO-3')
  expect(screen.getAllByText('Title DEMO-1')[0].closest('a')!.getAttribute('href')).toBe('#/needs-you/DEMO-1')
  expect(document.querySelector('.collapsed')!.textContent).toBe('▸ 2 not due yet')
})

it('test_desktop_release_detail_lists_items', async () => {
  mockWidth(1280)
  stubApi({ '/api/needs-you': ROWS })
  render(<NeedsYou selected="release:DEMO" />)
  await screen.findAllByText('Demo: 2 changes merged, not live')
  const pane = document.querySelector('.split .r') as HTMLElement
  expect(within(pane).getByText('Your answer')).toBeTruthy()
  expect(within(pane).getByRole('link', { name: 'second' }).getAttribute('target')).toBe('_blank')
})
