import { apiPost, AuthError } from '../api'
import ActivityLog from '../components/ActivityLog'
import { FLAG_TEXT } from '../components/Card'
import TaskCard from '../components/TaskCard'
import TokenPrompt from '../components/TokenPrompt'
import { useApi } from '../useApi'
import type { EpicDetailResponse } from '../types'

const GROUPS: [string, string][] = [
  ['todo', 'Todo'],
  ['in_progress', 'In progress'],
  ['blocked', 'Blocked'],
  ['review', 'Review'],
  ['done', 'Done'],
]

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
  return (
    <main className="epic-detail">
      {error && <p className="error" role="alert">{error}</p>}
      {epic && data && (
        <>
          <header>
            <h1>{epic.title}</h1>
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
          <ActivityLog events={data.events} />
        </>
      )}
    </main>
  )
}
