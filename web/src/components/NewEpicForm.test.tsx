import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NewEpicForm from './NewEpicForm'
import { clearToken } from '../token'
import { posts, PROJECTS, stubApi } from '../test/api'

beforeEach(() => clearToken())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const created = { id: 7, key: 'SAMPLE-E3', title: 'New thing' }

it('test_posts_the_right_body_and_reports_the_new_key', async () => {
  const f = stubApi({ '/api/health': { ok: true, principal: 'jo.doe@example.test' }, 'POST /api/projects/SAMPLE/epics': created })
  const onCreated = vi.fn()
  render(<NewEpicForm projects={PROJECTS} initialProject="SAMPLE" onCreated={onCreated} onCancel={() => {}} />)
  await waitFor(() => expect((screen.getByLabelText('Waiting on name') as HTMLInputElement).value).toBe('jo.doe'))
  expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('SAMPLE')
  expect((screen.getByLabelText('Stage') as HTMLSelectElement).value).toBe('idea')
  expect([...(screen.getByLabelText('Stage') as HTMLSelectElement).options].map((o) => o.value))
    .toEqual(['idea', 'spec', 'plan', 'build', 'review', 'ship'])
  await userEvent.type(screen.getByLabelText('Title'), 'New thing')
  await userEvent.selectOptions(screen.getByLabelText('Stage'), 'spec')
  await userEvent.type(screen.getByLabelText('Goal'), 'Make it work')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith('SAMPLE-E3'))
  expect(posts(f)).toEqual([{ url: '/api/projects/SAMPLE/epics',
    body: { title: 'New thing', stage: 'spec', waiting_on: 'human:jo.doe', goal: 'Make it work' } }])
})

it('test_agent_waiting_on_and_goal_omitted_when_blank', async () => {
  const f = stubApi({ '/api/health': { ok: true, principal: 'ci-token' }, 'POST /api/projects/DEMO/epics': created })
  render(<NewEpicForm projects={PROJECTS} initialProject="DEMO" onCreated={() => {}} onCancel={() => {}} />)
  await waitFor(() => expect((screen.getByLabelText('Waiting on name') as HTMLInputElement).value).toBe('owner'))
  await userEvent.type(screen.getByLabelText('Title'), 'T')
  await userEvent.selectOptions(screen.getByLabelText('Waiting on kind'), 'agent')
  await userEvent.clear(screen.getByLabelText('Waiting on name'))
  await userEvent.type(screen.getByLabelText('Waiting on name'), 'builder')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  await waitFor(() => expect(posts(f)).toHaveLength(1))
  expect(posts(f)[0].body).toEqual({ title: 'T', stage: 'idea', waiting_on: 'agent:builder' })
})

it('test_requires_title_and_project', async () => {
  const f = stubApi({ '/api/health': { ok: true, principal: 'owner' } })
  render(<NewEpicForm projects={PROJECTS} initialProject="" onCreated={() => {}} onCancel={() => {}} />)
  expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(posts(f)).toHaveLength(0)
  expect(screen.getByRole('alert').textContent).toMatch(/title/i)
  await userEvent.type(screen.getByLabelText('Title'), 'T')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(posts(f)).toHaveLength(0)
  expect(screen.getByRole('alert').textContent).toMatch(/project/i)
})

it('test_prefills_title', () => {
  stubApi({})
  render(<NewEpicForm projects={PROJECTS} initialProject="DEMO" initialTitle="From item" onCreated={() => {}} onCancel={() => {}} />)
  expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('From item')
})
