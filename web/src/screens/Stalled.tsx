import TokenPrompt from '../components/TokenPrompt'
import { useApi } from '../useApi'
import type { StalledRow, WaitingGroup } from '../types'

const GROUPS: [WaitingGroup, string][] = [
  ['agent', 'Waiting on agent'],
  ['human', 'Waiting on you'],
  ['source', 'Waiting on source'],
]

export default function Stalled() {
  const { data, needsAuth, error, load } = useApi<StalledRow[]>('/api/stalled', 'Could not load.')
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  const rows = data ?? []
  return (
    <main className="list">
      {error && <p className="error" role="alert">{error}</p>}
      {GROUPS.map(([g, label]) => {
        const rs = rows.filter((r) => r.waiting_group === g)
        if (rs.length === 0) return null
        return (
          <section key={g}>
            <h2>{label}</h2>
            <ul>
              {rs.map((r) => (
                <li key={`${r.kind}:${r.id}`}>
                  {r.kind === 'epic' ? (
                    <a href={`#/epic/${encodeURIComponent(r.ref)}`}>{r.title}</a>
                  ) : r.url ? (
                    <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
                  ) : (
                    <span>{r.title}</span>
                  )}
                  <span className="stalled-for">{`stalled ${Math.floor(r.stalled_for_hours)}h`}</span>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </main>
  )
}
