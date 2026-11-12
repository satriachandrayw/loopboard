import { apiPost, AuthError } from '../api'
import ActivityLog from '../components/ActivityLog'
import { FLAG_TEXT } from '../components/Card'
import TaskCard from '../components/TaskCard'
import TokenPrompt from '../components/TokenPrompt'
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
  return (
    <main className="epic-detail">
      {error && <p className="error" role="alert">{error}</p>}
      {epic && data && (
        <>
          <header>
            <h1>{epic.title}</h1>
            {epic.goal && <p className="goal">{epic.goal}</p>}
            {LINKS.some(([f]) => epic[f]) && (
              <p className="links">
                {LINKS.map(([f, label]) =>
                  epic[f] ? (
                    <a key={f} href={epic[f]!} target="_blank" rel="noreferrer">{label}</a>
                  ) : null,
                )}
              </p>
            )}
            <dl>
              <dt>Stage</dt><dd>{epic.stage ?? '-'}</dd>
              <dt>Next step</dt><dd>{epic.next_step ?? '-'}</dd>
              <dt>Owner</dt><dd>{epic.owner ?? '-'}</dd>
              <dt>Waiting on</dt><dd>{epic.waiting_on ?? '-'}</dd>
              <dt>Progress</dt><dd>{`${epic.progress.done}/${epic.progress.total}`}</dd>
            </dl>
            {epic.flags.map((f) => (
              <div key={f} className={`flag flag-${f}`}>{FLAG_TEXT[f] ?? f}</div>
            ))}
            {epic.flags.includes('awaiting_confirmation') && (
              <button type="button" onClick={() => void confirm()}>Confirm done</button>
            )}
          </header>
          {GROUPS.map(([g, label]) => (
            <section key={g}>
              <h2>{label}</h2>
              {(data.tasks[g] ?? []).map((t) => (
                <TaskCard key={t.id} task={t} />
              ))}
            </section>
          ))}
          {relations.length > 0 && (
            <section className="relations">
              <h2>Relations</h2>
              <ul>
                {relations.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </section>
          )}
          <ActivityLog events={data.events} />
        </>
      )}
    </main>
  )
}
