import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import Card from './Card'
import type { Card as CardT } from '../types'

const base: CardT = {
  id: 1, key: 'DEMO-E1', title: 'Epic', project_key: 'DEMO', column: 'todo',
  stage: 'build', progress: { done: 2, total: 4 }, owner: null,
  waiting_on: 'agent:a', waiting_since: 1000, stalled: false, flags: [], review_owner: null,
}
afterEach(cleanup)
const show = (c: Partial<CardT>) =>
  render(<Card card={{ ...base, ...c }} nowSeconds={1000 + 3 * 3600 + 5} onMove={() => {}} />)

it('test_waiting_class_by_prefix', () => {
  for (const [w, cls] of [['human:owner', 'wait-human'], ['agent:a', 'wait-agent'], ['source:CI', 'wait-source']]) {
    const { container, unmount } = show({ waiting_on: w })
    expect(container.querySelector('.' + cls)).not.toBeNull()
    unmount()
  }
})

it('test_stalled_class', () => {
  const { container } = show({ stalled: true })
  expect(container.querySelector('.card.stalled')).not.toBeNull()
})

it('test_flags_text', () => {
  show({ flags: ['awaiting_approval', 'awaiting_confirmation', 'blocked_needs_input', 'blocked', 'merged_not_live'], review_owner: 'human' })
  for (const t of ['awaiting your approval', 'awaiting your confirmation', 'blocked: needs your input', 'blocked', 'merged, not live', 'review · you'])
    expect(screen.getByText(t)).toBeTruthy()
})

it('test_progress_text_2_of_4', () => {
  show({})
  expect(screen.getByText('2/4')).toBeTruthy()
  expect(screen.getByText('waiting 3h')).toBeTruthy()
  expect(screen.getByText('build')).toBeTruthy()
  expect(screen.getByText('DEMO')).toBeTruthy()
})

it('test_title_links_to_epic_detail', () => {
  show({ key: 'DEMO-E1', title: 'Linked epic' })
  const a = screen.getByText('Linked epic').closest('a')!
  expect(a.getAttribute('href')).toBe('#/epic/DEMO-E1')
})
