import { useState } from 'react'
import { apiPost, ApiError, AuthError } from '../api'
import ActivityLog from '../components/ActivityLog'
import Menu from '../components/Menu'
import TokenPrompt from '../components/TokenPrompt'
import { announceChange, epicHref, FLAG_TEXT, RED_FLAGS, STATUS_TEXT, TASK_COLUMNS, waitKind, who } from '../format'
import { useApi } from '../useApi'
import type { TaskDetailResponse, TaskLink } from '../types'

const SOURCE: Record<string, [string, string]> = { kanban: ['🗂', 'Kanban card'], github: ['⑂', 'PR'] }

// The link's own state as the mockup words it: merged PRs say whether they are live yet.
function linkState(l: TaskLink): [string, string] {
  if (l.merged_at) return l.live_at ? ['live', 'done'] : ['merged, not live', 'review']
  return [l.category.replaceAll('_', ' '), l.category]
}

function LinkRows({ links }: { links: TaskLink[] }) {
  return (
    <table className="t">
      <tbody>
        {links.map((l) => {
          const [icon, word] = SOURCE[l.source] ?? ['', l.source]
          const [state, cat] = linkState(l)
          const label = `${icon ? `${icon} ` : ''}${word} "${l.title}"`
          return (
            <tr key={l.id}>
              <td>{l.url ? <a href={l.url} target="_blank" rel="noreferrer">{label}</a> : label}</td>
              <td className="st"><span className={`status st-${cat}`}>{state}</span></td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default function TaskDetail({ taskKey }: { taskKey: string }) {
  const k = encodeURIComponent(taskKey)
  const { data, needsAuth, setNeedsAuth, error, setError, load } =
    useApi<TaskDetailResponse>(`/api/tasks/${k}`, 'Could not load the task.')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  const act = async (path: string, body: unknown, failure: string) => {
    setBusy(true)
    try {
      await apiPost(`/api/tasks/${k}/${path}`, body)
      setError(null)
      await load()
      announceChange()
    } catch (e) {
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError(e instanceof ApiError && e.status === 403 ? 'Only a human can confirm a task is done.' : failure)
    } finally {
      setBusy(false)
      setAsking(false)
    }
  }

  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  const t = data
  const linked = t ? Object.keys(t.links_summary ?? {}).length > 0 : false
  const kind = waitKind(t?.waiting_on)
  return (
    <main className="screen list task-detail">
      {error && <p className="error" role="alert">{error}</p>}
      {t && (
        <>
          <header className="top">
            <div className="dh">
              <span className="key">{t.key}</span>
              <span className={`typ${t.type === 'bug' ? ' bug' : ''}`}>{t.type}</span>
              <span className={`status st-${t.status}`}>{STATUS_TEXT[t.status] ?? t.status}</span>
              {t.priority !== 'medium' && <span className="lbl">{`${t.priority} priority`}</span>}
            </div>
            <h1 className="t">{t.summary}</h1>
            <p className="s">
              {t.epic_key ? <>Epic <a href={epicHref(t.epic_key)}>{t.epic_key}</a></> : 'No epic'}
              {` · owner ${t.owner}`}
              {t.waiting_on && <>{' · waiting on '}<span className={kind ? `wait-${kind}` : undefined}>{who(t.waiting_on)}</span></>}
              {` · reporter ${t.reporter}`}
            </p>
          </header>
          <div className="body">
            <h2 className="sec">Description</h2>
            <div className="card box">
              <p className="goal">{t.description}</p>
              <p className="dw">{`Done when: ${t.done_when}`}</p>
              {t.refs.length > 0 && <p className="dw">{`Refs: ${t.refs.join(', ')}`}</p>}
            </div>
            <h2 className="sec">Links (status comes from these)</h2>
            <div className="card box">
              {t.links.length ? <LinkRows links={t.links} /> : <p className="s none">No links yet. Status moves by hand.</p>}
            </div>
            <p className="note reason">{t.reason}</p>
            {(t.flags.length > 0 || t.stalled) && (
              <div className="foot">
                {t.stalled && <span className="flag flag-red">stalled</span>}
                {t.flags.map((f) => (
                  <span key={f} className={`flag flag-${f}${RED_FLAGS.has(f) ? ' flag-red' : ''}`}>{FLAG_TEXT[f] ?? f.replaceAll('_', ' ')}</span>
                ))}
              </div>
            )}
            {t.status !== 'canceled' && (
              <div className="btns">
                {t.flags.includes('awaiting_confirmation') && (
                  <button type="button" className="btn" disabled={busy}
                    onClick={() => void act('confirm-done', undefined, 'Confirm failed.')}>Confirm done</button>
                )}
                {!linked && (
                  <Menu label="Move ▾" disabled={busy}
                    items={TASK_COLUMNS.filter(([s]) => s !== t.status).map(([s, label]) => ({
                      label, onSelect: () => void act('status', { status: s }, 'Move failed.'),
                    }))} />
                )}
                {asking ? (
                  <>
                    <button type="button" className="btn danger" disabled={busy}
                      onClick={() => void act('status', { status: 'canceled' }, 'Cancel failed.')}>{`Yes, cancel ${t.key}`}</button>
                    <button type="button" className="btn g" onClick={() => setAsking(false)}>Keep it</button>
                  </>
                ) : (
                  <button type="button" className="btn g" disabled={busy} onClick={() => setAsking(true)}>Cancel task</button>
                )}
              </div>
            )}
            <ActivityLog events={t.events} />
          </div>
        </>
      )}
    </main>
  )
}
