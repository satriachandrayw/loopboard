import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NewTaskForm from './NewTaskForm'
import { clearToken } from '../token'
import { board, epicCard, json, posts, PROJECTS, stubApi, taskView } from '../test/api'

beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const BOARD = board({
  todo: [epicCard(1, 'todo', { title: 'Demo epic' }), epicCard(2, 'todo', { key: 'SAMPLE-E1', title: 'Sample epic', project_key: 'SAMPLE' })],
  done: [epicCard(3, 'done', { title: 'Old epic' })],
})

const field = (name: RegExp) => screen.getByLabelText(name)

it('test_new_task_form_required_fields_and_body', async () => {
  const f = stubApi({ '/api/board': BOARD, 'POST /api/projects/DEMO/tasks': taskView(7, 'todo') })
  const created = vi.fn()
  render(<NewTaskForm projects={PROJECTS} initialProject="DEMO" onCreated={created} onCancel={() => {}} />)
  const marks = [...document.querySelectorAll('.field > span:first-child')]
    .filter((s) => s.querySelector('i.req')).map((s) => s.firstChild!.textContent!.trim())
  expect(marks).toEqual(['Project', 'Type', 'Summary', 'Description', 'Done when', 'Owner', 'Waiting on'])
  const create = screen.getByRole('button', { name: 'Create task' })
  const expectError = async (msg: string) => {
    await userEvent.click(create)
    expect((await screen.findByRole('alert')).textContent).toBe(msg)
  }
  await expectError('A summary is required.')
  await userEvent.type(field(/^Summary/), '  Landing page  ')
  await expectError('Add a description: what this task is.')
  await userEvent.type(field(/^Description/), 'One page layout.')
  await expectError('Add a "Done when" line.')
  await userEvent.type(field(/^Done when/), 'It is live.')
  await userEvent.clear(field(/^Owner/))
  await expectError('Say who owns it.')
  await userEvent.type(field(/^Owner/), 'coder')
  await userEvent.clear(screen.getByLabelText('Waiting on name'))
  await expectError('Say who it waits on.')
  await userEvent.type(screen.getByLabelText('Waiting on name'), 'coder')
  await userEvent.selectOptions(screen.getByLabelText('Waiting on kind'), 'agent')
  await userEvent.type(field(/^Refs/), 'ops-1')
  await expectError('Refs look like ABC-123.')
  await userEvent.clear(field(/^Refs/))
  await userEvent.type(field(/^Refs/), 'OPS-1, OPS-22')
  // Epic picker: open epics of the project, then No epic.
  const epic = field(/^Epic/) as HTMLSelectElement
  expect([...epic.options].map((o) => o.textContent)).toEqual(['No epic', 'DEMO-E1 · Demo epic'])
  await userEvent.selectOptions(epic, 'DEMO-E1')
  await userEvent.selectOptions(field(/^Type/), 'bug')
  await userEvent.selectOptions(field(/^Priority/), 'high')
  await userEvent.click(create)
  await waitFor(() => expect(created).toHaveBeenCalledWith('DEMO-7'))
  expect(posts(f)).toEqual([{ url: '/api/projects/DEMO/tasks', body: {
    summary: 'Landing page', description: 'One page layout.', done_when: 'It is live.', owner: 'coder',
    waiting_on: 'agent:coder', type: 'bug', priority: 'high', epic_key: 'DEMO-E1', refs: ['OPS-1', 'OPS-22'],
  } }])
})

it('test_new_task_form_needs_a_project_and_shows_server_failure', async () => {
  stubApi({ '/api/board': BOARD, 'POST /api/projects/SAMPLE/tasks': json({ detail: 'x' }, 422) })
  render(<NewTaskForm projects={PROJECTS} initialSummary="From a card" onCreated={() => {}} onCancel={() => {}} />)
  await userEvent.type(field(/^Description/), 'd')
  await userEvent.type(field(/^Done when/), 'w')
  await userEvent.click(screen.getByRole('button', { name: 'Create task' }))
  expect((await screen.findByRole('alert')).textContent).toBe('Choose a project.')
  await userEvent.selectOptions(field(/^Project/), 'SAMPLE')
  expect([...(field(/^Epic/) as HTMLSelectElement).options].map((o) => o.textContent)).toEqual(['No epic', 'SAMPLE-E1 · Sample epic'])
  await userEvent.click(screen.getByRole('button', { name: 'Create task' }))
  expect((await screen.findByRole('alert')).textContent).toBe('Could not create the task.')
})
