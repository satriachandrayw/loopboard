import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it } from 'vitest'
import TaskCard from './TaskCard'
import { taskView } from '../test/api'
import type { TaskView } from '../types'

afterEach(() => { cleanup(); window.location.hash = '' })

const NOW = 100 * 3600
const show = (extra: Record<string, unknown>, draggable = false) =>
  render(<TaskCard task={taskView(7, 'review', extra) as TaskView} nowSeconds={NOW} draggable={draggable} />)

it('test_task_card_links_summary_and_flags', async () => {
  const { container } = show({
    links_summary: { kanban: { count: 1, state: 'done' }, github: { count: 2, state: 'merged' } },
    flags: ['merged_not_live', 'blocked'], waiting_on: 'human:owner', waiting_since: NOW - 6 * 3600, refs: ['OPS-8001'],
  })
  expect(screen.getByText('DEMO-7')).toBeTruthy()
  expect(screen.getByText('task').className).toContain('typ')
  expect(screen.getByRole('link', { name: 'Task 7' }).getAttribute('href')).toBe('#/task/DEMO-7')
  expect(container.querySelector('.links')!.textContent).toBe('🗂 1 card done · ⑂ 2 PRs merged · ref OPS-8001')
  expect(container.querySelector('.wait-human')!.textContent).toBe('you · 6h')
  expect(screen.getByText('merged, not live').className).not.toContain('flag-red')
  expect(screen.getByText('blocked').className).toContain('flag-red')
  expect(container.querySelector('article')!.getAttribute('draggable')).toBe('false')
  await userEvent.click(container.querySelector('article')!)
  expect(window.location.hash).toBe('#/task/DEMO-7')
})

it('test_task_card_without_links_bug_and_stalled', () => {
  const { container } = show({ type: 'bug', stalled: true, waiting_since: NOW - 3 * 86400 }, true)
  expect(screen.getByText('bug').className).toContain('bug')
  expect(container.querySelector('.links')!.textContent).toBe('no links · moved by hand')
  expect(container.querySelector('article')!.className).toContain('stalled')
  expect(container.querySelector('.stl')!.textContent).toBe('3d')
  expect(container.querySelector('article')!.getAttribute('draggable')).toBe('true')
  cleanup()
  const t = render(<TaskCard task={taskView(8, 'todo') as TaskView} nowSeconds={NOW} draggable />)
  expect(t.container.querySelector('.links')!.textContent).toBe('no links yet')
  expect(t.container.querySelector('.wait-agent')!.textContent).toContain('coder')
})
