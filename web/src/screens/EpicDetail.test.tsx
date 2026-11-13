import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EpicDetail from './EpicDetail'
import { clearToken } from '../token'
import { board, epicCard, posts, PROJECTS, stubApi, taskView } from '../test/api'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
function detail(flags: string[] = []) {
  return {
    epic: { id: 1, key: 'DEMO-E1', title: 'Epic', project_key: 'DEMO', column: 'review', stage: 'build', progress: { done: 1, total: 2 }, owner: null, waiting_on: 'human:o', waiting_since: 1, stalled: false, flags, review_owner: 'human', goal: null, next_step: null },
    tasks: [
      taskView(1, 'todo', { summary: 'T-todo' }),
      taskView(2, 'in_progress', { summary: 'T-prog', links_summary: { kanban: { count: 1, state: 'running' }, github: { count: 2, state: 'open' } } }),
      taskView(4, 'review', { summary: 'T-review', waiting_on: 'human:owner', owner: 'owner' }),
    ],
    events: [
      { id: 2, at: 200, actor: 'a', via: 'api', kind: 'newer', payload: {} },
      { id: 1, at: 100, actor: 'a', via: 'api', kind: 'older', payload: {} },
    ],
  }
}
beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('test_epic_detail_lists_tasks_and_add_task', async () => {
  let created = false
  const f = stubApi({
    '/api/epics/DEMO-E1': () => created ? { ...detail(), tasks: [...detail().tasks, taskView(5, 'todo', { summary: 'T-new' })] } : detail(),
    '/api/projects': PROJECTS,
    '/api/board': board({ todo: [epicCard(1, 'todo', { title: 'Epic' })] }),
    'POST /api/projects/DEMO/tasks': () => { created = true; return taskView(5, 'todo') },
  })
  render(<EpicDetail epicKey="DEMO-E1" />)
  await screen.findByText('T-todo')
  expect(screen.getByText('Tasks · 1/2 done')).toBeTruthy()
  const rows = screen.getAllByRole('row')
  expect(rows.map((r) => r.querySelector('.key')?.textContent ?? r.textContent)).toEqual(['DEMO-1', 'DEMO-2', 'DEMO-4', '+ Add task'])
  const prog = rows[1]
  expect(prog.querySelector('a')!.getAttribute('href')).toBe('#/task/DEMO-2')
  expect([...prog.querySelectorAll('.chip-link')].map((c) => c.textContent)).toEqual(['🗂 1 card running', '⑂ 2 PRs open'])
  expect(prog.querySelector('.status')!.textContent).toBe('In progress')
  expect(rows[2].querySelector('.wait-human')!.textContent).toBe('you')
  await userEvent.click(screen.getByRole('button', { name: '+ Add task' }))
  expect((screen.getByLabelText(/^Project/) as HTMLSelectElement).value).toBe('DEMO')
  await waitFor(() => expect((screen.getByLabelText(/^Epic/) as HTMLSelectElement).value).toBe('DEMO-E1'))
  await userEvent.type(screen.getByLabelText(/^Summary/), 'T-new')
  await userEvent.type(screen.getByLabelText(/^Description/), 'd')
  await userEvent.type(screen.getByLabelText(/^Done when/), 'w')
  await userEvent.click(screen.getByRole('button', { name: 'Create task' }))
  await screen.findByText('T-new')
  expect(posts(f)[0].body.epic_key).toBe('DEMO-E1')
  expect(screen.queryByRole('dialog')).toBeNull()
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

it('test_goal_links_and_relations', async () => {
  const d = detail()
  Object.assign(d.epic, { goal: 'Ship the thing', home_url: 'https://h.test', spec_url: null, plan_url: 'https://p.test' })
  Object.assign(d, {
    relations: [
      { id: 1, kind: 'blocks', from_type: 'task', from_id: 2, to_type: 'epic', to_id: 9 },
      { id: 2, kind: 'blocks', from_type: 'epic', from_id: 7, to_type: 'epic', to_id: 1 },
    ],
  })
  vi.stubGlobal('fetch', vi.fn(async () => json(d)))
  render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText('Ship the thing'))
  expect(screen.getByText('Ship the thing').previousElementSibling!.textContent).toBe('Description')
  expect(screen.queryByText('Goal')).toBeNull()
  for (const [name, href] of [['Home', 'https://h.test'], ['Plan', 'https://p.test']]) {
    const a = screen.getByRole('link', { name })
    expect(a.getAttribute('href')).toBe(href)
    expect(a.getAttribute('target')).toBe('_blank')
    expect(a.getAttribute('rel')).toBe('noreferrer')
  }
  expect(screen.queryByRole('link', { name: 'Spec' })).toBeNull()
  expect(screen.getByText('T-prog blocks epic #9')).toBeTruthy()
  expect(screen.getByText('This epic is blocked by epic #7')).toBeTruthy()
})

it('test_no_relations_section_when_empty', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ ...detail(), relations: [] })))
  render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText('T-todo'))
  expect(screen.queryByRole('heading', { name: 'Relations' })).toBeNull()
})

it('test_stage_track_marks_past_and_current_stage', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(detail())))
  const { container } = render(<EpicDetail epicKey="DEMO-E1" />)
  await waitFor(() => screen.getByText('T-todo'))
  const segs = [...container.querySelectorAll('.stage span')].map((s) => s.className)
  expect(segs).toEqual(['d', 'd', 'd', 'c', '', '', ''])
  expect(screen.getByLabelText('Stage: build')).toBeTruthy()
})
