import { apiPost, AuthError } from '../api'
import ActivityLog from '../components/ActivityLog'
import TaskCard from '../components/TaskCard'
import TokenPrompt from '../components/TokenPrompt'
import { FLAG_TEXT, RED_FLAGS, waitKind } from '../format'
import { useApi } from '../useApi'
import type { EpicDetailResponse, Relation, Task } from '../types'

const GROUPS: [string, string][] = [
  ['todo', 'Todo'],
  ['in_progress', 'In progress'],
  ['blocked', 'Blocked'],
  ['review', 'Review'],
  ['done', 'Done'],
]

const LINKS: ['home_url' | 'spec_url' | 'plan_url', string][] = [
  ['home_url', 'Home'],
  ['spec_url', 'Spec'],
  ['plan_url', 'Plan'],
]

const STAGES = ['idea', 'spec', 'plan', 'build', 'review', 'ship', 'done']

// The stage track: stages before the current one filled, the current one highlighted.
function StageTrack({ stage, column }: { stage: string | null; column: string }) {
  const at = column === 'done' ? STAGES.length - 1 : STAGES.indexOf(stage ?? '')
  return (
    <div className="stage-track" aria-label={`Stage: ${column === 'done' ? 'done' : (stage ?? 'none')}`}>
      <div className="stage">
        {STAGES.map((s, i) => (
          <span key={s} className={i < at ? 'd' : i === at ? 'c' : undefined} />
        ))}
      </div>
      <div className="stagel">
        {STAGES.map((s) => <span key={s}>{s[0].toUpperCase() + s.slice(1)}</span>)}
      </div>
    </div>
  )
}

// "X blocks Y" lines, naming this epic and its tasks; other ends show as `<type> #<id>`.
function relationLines(epicId: number, tasks: Task[], relations: Relation[]): string[] {
  const titles = new Map(tasks.map((t) => [t.id, t.title]))
  const mine = (type: string, id: number) => (type === 'epic' ? id === epicId : titles.has(id))
  const name = (type: string, id: number) =>
    type === 'epic' ? (id === epicId ? 'This epic' : `epic #${id}`) : (titles.get(id) ?? `item #${id}`)
  return relations.map((r) =>
    mine(r.from_type, r.from_id)
      ? `${name(r.from_type, r.from_id)} blocks ${name(r.to_type, r.to_id)}`
      : `${name(r.to_type, r.to_id)} is blocked by ${name(r.from_type, r.from_id)}`,
  )
}

export default function EpicDetail({ epicKey }: { epicKey: string }) {
  const k = encodeURIComponent(epicKey)
  const { data, needsAuth, setNeedsAuth, error, setError, load } = useApi<EpicDetailResponse>(`/api/epics/${k}`, 'Could not load the epic.')
  const confirm = async () => {
    try {
      await apiPost(`/api/epics/${k}/confirm-done`)
      await load()
    } catch (e) {
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError('Confirm failed.')
    }
  }
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  const epic = data?.epic
  const relations = epic && data ? relationLines(epic.id, Object.values(data.tasks).flat(), data.relations ?? []) : []
  const kind = waitKind(epic?.waiting_on)
  return (
    <main className="screen list epic-detail">
      {error && <p className="error" role="alert">{error}</p>}
      {epic && data && (
        <>
          <header className="top">
            <h1 className="t"><span className="key">{epic.key}</span> {epic.title}</h1>
            <p className="s">
              {[epic.project_key, epic.owner && `owner ${epic.owner}`].filter(Boolean).join(' · ')}
              {LINKS.some(([f]) => epic[f]) && (
                <span className="links">
                  {LINKS.map(([f, label]) =>
                    epic[f] ? (
                      <a key={f} href={epic[f]!} target="_blank" rel="noreferrer">{label}</a>
                    ) : null,
                  )}
                </span>
              )}
            </p>
          </header>
          <div className="body">
            <StageTrack stage={epic.stage} column={epic.column} />
            <div className="card facts">
              {epic.goal && (<><div className="meta">Description</div><p className="next goal">{epic.goal}</p></>)}
              <div className="meta">Next step</div>
              <p className="next">{epic.next_step ?? '-'}</p>
              <dl>
                <dt>Waiting on</dt>
                <dd className={kind ? `wait-${kind}` : undefined}>{epic.waiting_on ?? '-'}</dd>
                <dt>Progress</dt><dd>{`${epic.progress.done}/${epic.progress.total}`}</dd>
              </dl>
              {epic.progress.total > 0 && (
                <div className="pb" aria-hidden="true">
                  <i style={{ width: `${Math.round((100 * epic.progress.done) / epic.progress.total)}%` }} />
                </div>
              )}
              {(epic.flags.length > 0 || epic.stalled) && (
                <div className="foot">
                  {epic.stalled && <span className="flag flag-red">stalled</span>}
                  {epic.flags.map((f) => (
                    <span key={f} className={`flag flag-${f}${RED_FLAGS.has(f) ? ' flag-red' : ''}`}>{FLAG_TEXT[f] ?? f}</span>
                  ))}
                </div>
              )}
              {epic.flags.includes('awaiting_confirmation') && (
                <div className="btns">
                  <button type="button" className="btn" onClick={() => void confirm()}>Confirm done</button>
                </div>
              )}
            </div>
            <p className="sec">{`Tasks · ${epic.progress.done}/${epic.progress.total}`}</p>
            {GROUPS.map(([g, label]) => (
              <section key={g} className="task-group">
                <h2 className="sec">{label}</h2>
                <div className="card tasks">
                  {(data.tasks[g] ?? []).length === 0 && <p className="s none">None</p>}
                  {(data.tasks[g] ?? []).map((t) => (
                    <TaskCard key={t.id} task={t} />
                  ))}
                </div>
              </section>
            ))}
            {relations.length > 0 && (
              <section className="relations">
                <h2 className="sec">Relations</h2>
                <ul className="card">
                  {relations.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </section>
            )}
            <ActivityLog events={data.events} />
          </div>
        </>
      )}
    </main>
  )
}
