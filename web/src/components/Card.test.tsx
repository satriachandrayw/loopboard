import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import Card from './Card'
import { formatAge } from '../format'
import type { Card as CardT } from '../types'

const base: CardT = {
  id: 1, key: 'DEMO-E1', title: 'Epic', goal: null, project_key: 'DEMO', column: 'todo',
  stage: 'build', progress: { done: 2, total: 4 }, owner: null,
  waiting_on: 'agent:builder', waiting_since: 1000, stalled: false, flags: [], review_owner: null,
}
afterEach(cleanup)
const show = (c: Partial<CardT>) =>
  render(<Card card={{ ...base, ...c }} nowSeconds={1000 + 3 * 3600 + 5} onMove={() => {}} />)

it('test_human_wait_is_you_in_orange_class', () => {
  const { container } = show({ waiting_on: 'human:owner' })
  const w = container.querySelector('.wait-human')!
  expect(w.textContent).toBe('you · 3h')
})

it('test_agent_wait_names_the_agent_in_teal_class', () => {
  const { container } = show({ waiting_on: 'agent:builder' })
  expect(container.querySelector('.wait-agent')!.textContent).toBe('builder · 3h')
  expect(container.querySelector('.wait-human')).toBeNull()
})

it('test_source_wait_class', () => {
  const { container } = show({ waiting_on: 'source:CI' })
  expect(container.querySelector('.wait-source')!.textContent).toBe('CI · 3h')
})

it('test_backlog_shows_parked_age_muted', () => {
  const { container } = show({ column: 'backlog', waiting_on: 'human:owner', progress: { done: 0, total: 0 } })
  expect(container.querySelector('.wait-parked')!.textContent).toBe('parked 3h')
  expect(container.querySelector('.wait-human')).toBeNull()
  expect(container.querySelector('.pb')).toBeNull()
})

it('test_stalled_class_and_red_age', () => {
  const { container } = show({ stalled: true, waiting_on: 'human:owner' })
  expect(container.querySelector('.card.stalled')).not.toBeNull()
  expect(container.querySelector('.wait-human .stl')!.textContent).toBe('3h')
  cleanup()
  const r = show({ stalled: false })
  expect(r.container.querySelector('.card.stalled')).toBeNull()
})

it('test_flag_pills_with_blocked_in_red', () => {
  const { container } = show({ flags: ['awaiting_approval', 'awaiting_confirmation', 'blocked_needs_input', 'blocked', 'merged_not_live'], review_owner: 'human' })
  for (const t of ['awaiting your approval', 'awaiting your confirmation', 'blocked: needs your input', 'blocked', 'merged, not live', 'review · you'])
    expect(screen.getByText(t).classList.contains('flag')).toBe(true)
  expect(container.querySelector('.flag-blocked_needs_input.flag-red')).not.toBeNull()
  expect(container.querySelector('.flag-blocked.flag-red')).not.toBeNull()
  expect(container.querySelector('.flag-awaiting_approval.flag-red')).toBeNull()
})

it('test_first_line_key_stage_project_and_progress', () => {
  const { container } = show({})
  expect(container.querySelector('.top .key')!.textContent).toBe('DEMO-E1')
  expect(container.querySelector('.top .lbl')!.textContent).toBe('build')
  expect(container.querySelector('.top .proj')!.textContent).toBe('DEMO')
  expect(screen.getByText('2/4')).toBeTruthy()
  expect((container.querySelector('.pb i') as HTMLElement).style.width).toBe('50%')
})

it('test_title_links_to_epic_detail', () => {
  show({ key: 'DEMO-E1', title: 'Linked epic' })
  const a = screen.getByText('Linked epic').closest('a')!
  expect(a.getAttribute('href')).toBe('#/epic/DEMO-E1')
})

it('test_format_age', () => {
  expect(formatAge(30)).toBe('now')
  expect(formatAge(25 * 60)).toBe('25m')
  expect(formatAge(26 * 3600)).toBe('26h')
  expect(formatAge(48 * 3600)).toBe('2d')
})

it('test_card_shows_description_clamped', () => {
  const { container } = show({ goal: 'Ship the thing. '.repeat(120) })
  const d = container.querySelector('.desc')!
  expect(d.textContent).toContain('Ship the thing.')
  expect(d.className).toBe('desc')
  // Under the title, before the progress bar.
  expect(d.previousElementSibling!.className).toBe('ti')
  expect(d.nextElementSibling!.className).toBe('pb')
})

it('test_card_without_goal_has_no_description', () => {
  const { container } = show({ goal: null })
  expect(container.querySelector('.desc')).toBeNull()
  expect(container.textContent).not.toContain('null')
})
