import { vi } from 'vitest'

export const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

type Handler = unknown | ((url: string, init?: RequestInit) => unknown)

// Routes are keyed by "METHOD /path" or "/path" (any method); the query string is ignored.
// Unknown GETs answer [] and unknown writes answer {}.
export function stubApi(routes: Record<string, Handler>) {
  const f = vi.fn(async (u: string, init?: RequestInit) => {
    const path = String(u).split('?')[0]
    const method = init?.method ?? 'GET'
    const h = routes[`${method} ${path}`] ?? routes[path]
    if (h === undefined) return json(method === 'GET' ? [] : {})
    const v = typeof h === 'function' ? await (h as (u: string, i?: RequestInit) => unknown)(String(u), init) : h
    return v instanceof Response ? v : json(v)
  })
  vi.stubGlobal('fetch', f)
  return f
}

export const urls = (f: ReturnType<typeof stubApi>) => f.mock.calls.map((c) => String(c[0]))
export const posts = (f: ReturnType<typeof stubApi>) =>
  f.mock.calls.filter((c) => c[1]?.method === 'POST').map((c) => ({ url: String(c[0]), body: JSON.parse(String(c[1]!.body)) }))

export function mockMatchMedia(narrow: boolean) {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: narrow, media: q, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false,
  }))
}

export const PROJECTS = [
  { id: 1, key: 'DEMO', name: 'Demo', created_at: 1 },
  { id: 2, key: 'SAMPLE', name: 'Sample', created_at: 1 },
]

const COLS = [['backlog', 'Backlog'], ['todo', 'Todo'], ['in_progress', 'In progress'], ['review', 'Review'], ['done', 'Done']]

export const epicCard = (id: number, column: string, extra: Record<string, unknown> = {}) => ({
  id, key: `DEMO-E${id}`, title: `Epic ${id}`, project_key: 'DEMO', column, stage: 'build',
  progress: { done: 0, total: 1 }, owner: null, waiting_on: 'agent:a', waiting_since: 1, stalled: false,
  flags: [], review_owner: null, ...extra,
})

export function board(cards: Record<string, unknown[]> = {}, reviewCount?: number) {
  return {
    columns: COLS.map(([c, label]) => {
      const count = c === 'review' && reviewCount !== undefined ? reviewCount : (cards[c]?.length ?? 0)
      return { column: c, label, count, warn: c === 'review' && count >= 4, cards: cards[c] ?? [] }
    }),
  }
}
