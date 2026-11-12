export type WaitingGroup = 'agent' | 'human' | 'source'
export type ColumnId = 'backlog' | 'todo' | 'in_progress' | 'review' | 'done'

export interface Card {
  id: number
  key: string
  title: string
  project_key: string
  column: string
  stage: string | null
  progress: { done: number; total: number }
  owner: string | null
  waiting_on: string | null
  waiting_since: number | null
  stalled: boolean
  flags: string[]
  review_owner: 'human' | 'agent' | null
}

export interface ColumnData {
  column: string
  label: string
  count: number
  warn: boolean
  cards: Card[]
}

export interface BoardResponse {
  columns: ColumnData[]
}

export interface NeedsYouRow {
  kind: 'epic' | 'item'
  id: number
  ref: string
  title: string
  url?: string | null
  waiting_on: string | null
  waiting_since: number | null
  reasons: string[]
}

export interface StalledRow {
  kind: 'epic' | 'item'
  id: number
  ref: string
  title: string
  url?: string | null
  waiting_on: string | null
  waiting_group: WaitingGroup
  waiting_since: number | null
  stalled_for_hours: number
}

export interface UnfiledRow {
  id: number
  source: string
  external_id: string
  title: string
  url: string | null
  owner: string | null
  waiting_on: string | null
  last_activity_at: number
}

export interface Task {
  id: number
  ref: string
  title: string
  url: string | null
  waiting_on: string | null
  category: string
}

export interface EpicEvent {
  id: number
  at: number
  actor: string
  via: string
  kind: string
  payload: Record<string, unknown> | null
}

export interface EpicDetailResponse {
  epic: Card & { goal: string | null; next_step: string | null }
  tasks: Record<string, Task[]>
  events: EpicEvent[]
}
