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
