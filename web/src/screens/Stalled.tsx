import ProjectChips from '../components/ProjectChips'
import TokenPrompt from '../components/TokenPrompt'
import { epicHref, formatAge, taskHref, who } from '../format'
import { useProject, useProjects, withProject } from '../project'
import { useApi } from '../useApi'
import type { StalledRow, WaitingGroup } from '../types'

const GROUPS: [WaitingGroup, string][] = [
  ['agent', 'Waiting on agent'],
  ['human', 'Waiting on you'],
  ['source', 'Waiting on source'],
]
// Pill colour per group: teal agent, orange you, red source.
const PILL: Record<WaitingGroup, string> = { agent: 'agent', human: 'you', source: 'red' }

export default function Stalled() {
  const [project] = useProject()
  const projects = useProjects()
  const { data, needsAuth, error, load } = useApi<StalledRow[]>(withProject('/api/stalled', project), 'Could not load.')
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  const rows = Array.isArray(data) ? data : []
  return (
    <main className="screen list">
      <div className="top">
        <h1 className="t">Stalled</h1>
        <p className="s">{`No activity past the stall threshold · ${rows.length} ${rows.length === 1 ? 'item' : 'items'}`}</p>
      </div>
      <div className="filters"><ProjectChips projects={projects} /></div>
      <div className="body">
        {error && <p className="error" role="alert">{error}</p>}
        {data != null && rows.length === 0 && <p className="s none">Nothing is stalled.</p>}
        {GROUPS.map(([g, label]) => {
          const rs = rows.filter((r) => r.waiting_group === g)
          if (rs.length === 0) return null
          return (
            <section key={g}>
              <h2 className="sec">{label}</h2>
              <ul className="rows">
                {rs.map((r) => {
                  const name = who(r.waiting_on) ?? (g === 'human' ? 'you' : g)
                  return (
                    <li key={`${r.kind}:${r.id}`} className="card">
                      <div className="h">
                        <span className="ti">
                          {r.kind === 'epic' ? (
                            <a href={epicHref(r.ref)}>{r.title}</a>
                          ) : r.kind === 'task' ? (
                            <a href={taskHref(r.ref)}>{r.title}</a>
                          ) : r.url ? (
                            <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
                          ) : (
                            r.title
                          )}
                        </span>
                        <span className={`pill ${PILL[g]}`}>{`${name} · ${formatAge(r.stalled_for_hours * 3600)}`}</span>
                      </div>
                      <div className="meta">
                        <span className="src">{r.kind === 'item' ? (r.source ?? r.ref.split(':')[0]) : r.kind}</span>
                        {` ${r.kind === 'item' ? (r.external_id ?? r.ref) : r.ref}${r.kind === 'task' && r.epic_key ? ` · ${r.epic_key}` : ''}`}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </section>
          )
        })}
      </div>
    </main>
  )
}
