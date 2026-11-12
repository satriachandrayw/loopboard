import ProjectChips from '../components/ProjectChips'
import TokenPrompt from '../components/TokenPrompt'
import { ageSince, epicHref } from '../format'
import { useProject, useProjects, withProject } from '../project'
import { useApi } from '../useApi'
import type { NeedsYouRow } from '../types'

export default function NeedsYou() {
  const [project] = useProject()
  const projects = useProjects()
  const { data, needsAuth, error, load } = useApi<NeedsYouRow[]>(withProject('/api/needs-you', project), 'Could not load.')
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  const rows = Array.isArray(data) ? data : []
  return (
    <main className="screen list">
      <div className="top">
        <h1 className="t">Needs you</h1>
        <p className="s">{`${rows.length} ${rows.length === 1 ? 'item' : 'items'} waiting on you · oldest first`}</p>
      </div>
      <div className="filters"><ProjectChips projects={projects} /></div>
      <div className="body">
        {error && <p className="error" role="alert">{error}</p>}
        {data != null && rows.length === 0 && <p className="s none">Nothing needs you right now.</p>}
        <ul className="rows">
          {rows.map((r) => {
            const age = ageSince(r.waiting_since)
            const href = r.kind === 'epic' ? epicHref(r.ref) : r.url
            const ext = r.kind !== 'epic'
            return (
              <li key={`${r.kind}:${r.id}`} className="card">
                <div className="h">
                  <span className="ti">
                    {href ? <a href={href} {...(ext ? { target: '_blank', rel: 'noreferrer' } : {})}>{r.title}</a> : r.title}
                  </span>
                  {age && <span className="pill you">{age}</span>}
                </div>
                <div className="meta">
                  <span className="src">{r.kind === 'epic' ? 'epic' : r.ref.split(':')[0]}</span>
                  {` ${r.ref}`}
                </div>
                {r.reasons.length > 0 && <div className="next">{`→ ${r.reasons.join(' · ')}`}</div>}
                {href && (
                  <div className="btns">
                    <a className="btn" href={href} {...(ext ? { target: '_blank', rel: 'noreferrer' } : {})}>
                      {r.kind === 'epic' ? 'Open card' : 'Open ↗'}
                    </a>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </main>
  )
}
