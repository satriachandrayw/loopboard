const OPEN = new Set(['backlog', 'todo', 'in_progress', 'blocked', 'review'])

// Ages as the mockups show them: now, 25m, 26h, 3d.
export function formatAge(seconds: number): string {
  const s = Math.max(0, seconds)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 48 * 3600) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export const nowSeconds = () => Math.floor(Date.now() / 1000)

export const ageSince = (since: number | null | undefined, now = nowSeconds()) =>
  since == null ? null : formatAge(now - since)

// `human:jo` -> you, `agent:builder` -> builder, `source:CI` -> CI.
export function who(waitingOn: string | null | undefined): string | null {
  if (!waitingOn) return null
  if (waitingOn.startsWith('human:')) return 'you'
  const i = waitingOn.indexOf(':')
  return i >= 0 ? waitingOn.slice(i + 1) : waitingOn
}

export function waitKind(waitingOn: string | null | undefined): 'human' | 'agent' | 'source' | null {
  if (waitingOn?.startsWith('human:')) return 'human'
  if (waitingOn?.startsWith('agent:')) return 'agent'
  if (waitingOn?.startsWith('source:')) return 'source'
  return null
}

// An unfiled item is open unless done (or merged and live) or canceled.
export function isOpenItem(r: { category?: string; status_category?: string; live_at?: number | null }): boolean {
  const cat = r.category ?? r.status_category ?? 'todo'
  return OPEN.has(cat) && !r.live_at
}

// Tell the header to re-count its badges after a write.
export const REFRESH_EVENT = 'loopboard:refresh'
export const announceChange = () => window.dispatchEvent(new Event(REFRESH_EVENT))

export const FLAG_TEXT: Record<string, string> = {
  awaiting_approval: 'awaiting your approval',
  awaiting_confirmation: 'awaiting your confirmation',
  blocked_needs_input: 'blocked: needs your input',
  blocked: 'blocked',
  merged_not_live: 'merged, not live',
}
// Blocked flags are red; the rest are orange (they wait on you).
export const RED_FLAGS = new Set(['blocked', 'blocked_needs_input'])

export const epicHref = (key: string) => `#/epic/${encodeURIComponent(key)}`

export const REVIEW_LIMIT = 3

export const COLUMN_RULES: Record<string, string> = {
  backlog: 'Parked ideas. Nothing starts here.',
  todo: 'You said go. Spec and plan get written and approved.',
  in_progress: 'Agents building. Moves by itself.',
  review: 'Handed over to review, merge and deploy.',
  done: 'Live, not just merged. Hides after 7 days.',
}

export const taskHref = (key: string) => `#/task/${encodeURIComponent(key)}`

export const TASK_COLUMNS: [string, string][] = [
  ['todo', 'Todo'], ['in_progress', 'In progress'], ['review', 'Review'], ['done', 'Done'],
]

const LINK_WORDS: Record<string, [string, string, string]> = {
  kanban: ['🗂', 'card', 'cards'],
  github: ['⑂', 'PR', 'PRs'],
}

// `🗂 1 card done · ⑂ 2 PRs merged`; other sources by name.
export function linksText(summary: Record<string, { count: number; state: string }>): string {
  return Object.entries(summary)
    .map(([src, { count, state }]) => {
      const w = LINK_WORDS[src]
      return w ? `${w[0]} ${count} ${count === 1 ? w[1] : w[2]} ${state}` : `${count} ${src} ${state}`
    })
    .join(' · ')
}
