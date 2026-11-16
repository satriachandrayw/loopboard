import { useState } from 'react'
import type { MouseEvent } from 'react'
import { apiPost, ApiError, AuthError } from '../api'
import AnswerBox, { KIND_LABEL, KindLabel, Question } from '../components/AnswerBox'
import ProjectChips from '../components/ProjectChips'
import TokenPrompt from '../components/TokenPrompt'
import { ageSince, announceChange, epicHref, taskHref } from '../format'
import { useProject, useProjects, withProject } from '../project'
import { useApi } from '../useApi'
import { useWide } from '../useNarrow'
import TaskDetail from './TaskDetail'
import type { NeedsYouRow } from '../types'

const GROUPS = ['decide', 'review', 'release', 'confirm', 'later'] as const

export const needsYouHref = (ref: string) => `#/needs-you/${encodeURIComponent(ref)}`

function pageHref(r: NeedsYouRow): string | null {
  if (r.kind === 'task') return taskHref(r.ref)
  if (r.kind === 'epic') return epicHref(r.ref)
  return null
}

function ReleaseItems({ row }: { row: NeedsYouRow }) {
  return (
    <ul className="rel-items">
      {(row.items ?? []).map((i) => (
        <li key={i.ref} className="lnk">
          <span className="src">{i.ref.split(':')[0]}</span>
          {i.url ? <a href={i.url} target="_blank" rel="noopener noreferrer">{i.title}</a> : <span>{i.title}</span>}
        </li>
      ))}
    </ul>
  )
}

interface RowProps {
  row: NeedsYouRow
  wide: boolean
  selected: boolean
  busy: boolean
  onConfirm: (ref: string) => void
}

function Row({ row: r, wide, selected, busy, onConfirm }: RowProps) {
  const [open, setOpen] = useState(false)
  const age = ageSince(r.waiting_since)
  const href = wide ? needsYouHref(r.ref) : pageHref(r)
  const select = (e: MouseEvent) => {
    if (!wide || (e.target as HTMLElement).closest('a, button')) return
    window.location.hash = needsYouHref(r.ref)
  }
  const n = r.items?.length ?? 0
  return (
    <li className={`card ask${selected ? ' sel' : ''}`} onClick={select}>
      <div className="h">
        <KindLabel kind={r.ask_kind} />
        <span className="ti">{href ? <a href={href}>{r.title}</a> : r.title}</span>
        {age && <span className="pill you">{age}</span>}
      </div>
      <div className="meta">
        {r.kind === 'release' ? (
          <><span className="src">{r.project_key}</span>{` ${n} ${n === 1 ? 'change' : 'changes'} merged, not live`}</>
        ) : (
          <><span className="src">{r.kind}</span>{` ${r.ref}${r.kind === 'task' && r.epic_key ? ` · ${r.epic_key}` : ''}`}</>
        )}
      </div>
      <Question ask={r}>{r.context && <p className="ctx">{r.context}</p>}</Question>
      {r.kind === 'task' && r.reasons.includes('awaiting your confirmation') && (
        <div className="btns">
          <button type="button" className="btn" disabled={busy} onClick={() => onConfirm(r.ref)}>Confirm done</button>
        </div>
      )}
      {r.kind === 'release' ? (
        <>
          <button type="button" className="more" aria-expanded={open} onClick={() => setOpen(!open)}>Context and details ›</button>
          {open && <ReleaseItems row={r} />}
        </>
      ) : !wide && href && <a className="more" href={href}>Context and details ›</a>}
    </li>
  )
}

function Detail({ row }: { row: NeedsYouRow }) {
  if (row.kind === 'task') return <TaskDetail key={row.ref} taskKey={row.ref} embedded />
  const age = ageSince(row.waiting_since)
  return (
    <section className="screen list task-detail">
      <header className="top">
        <div className="key">{[row.ref, row.kind, age && `waiting on you ${age}`].filter(Boolean).join(' · ')}</div>
        <h1 className="t">{row.title}</h1>
      </header>
      <div className="body">
        <AnswerBox ask={row} />
        {row.kind === 'release' ? (
          <section className="card box">
            <h2 className="bh">Merged, not live</h2>
            <ReleaseItems row={row} />
          </section>
        ) : (
          <section className="card box">
            <h2 className="bh">Context</h2>
            {row.context && <p className="goal">{row.context}</p>}
            <p className="dw"><a href={epicHref(row.ref)}>Open the epic ›</a></p>
          </section>
        )}
      </div>
    </section>
  )
}

export default function NeedsYou({ selected }: { selected?: string | null }) {
  const [project] = useProject()
  const projects = useProjects()
  const wide = useWide()
  const { data, needsAuth, setNeedsAuth, error, setError, load } =
    useApi<NeedsYouRow[]>(withProject('/api/needs-you', project), 'Could not load.')
  const [busy, setBusy] = useState(false)
  const [laterOpen, setLaterOpen] = useState(false)
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  const rows = Array.isArray(data) ? data : []
  const later = rows.filter((r) => r.ask_kind === 'later')
  const nowCount = rows.length - later.length
  const sel = wide ? (rows.find((r) => r.ref === selected) ?? rows.find((r) => r.ask_kind !== 'later') ?? null) : null

  const confirm = async (ref: string) => {
    setBusy(true)
    try {
      await apiPost(`/api/tasks/${encodeURIComponent(ref)}/confirm-done`)
      await load()
      announceChange()
    } catch (e) {
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError(e instanceof ApiError && e.status === 403 ? 'Only a human can confirm a task is done.' : 'Confirm failed.')
    } finally {
      setBusy(false)
    }
  }

  const row = (r: NeedsYouRow) => (
    <Row key={`${r.kind}:${r.ref}`} row={r} wide={wide} selected={sel?.ref === r.ref} busy={busy}
      onConfirm={(ref) => void confirm(ref)} />
  )
  const list = (
    <main className="screen list needs-you">
      <div className="top">
        <h1 className="t">Needs you</h1>
        <p className="s">
          {rows.length === 0
            ? '0 items waiting on you · oldest first'
            : `${nowCount} to answer now · ${later.length} later · oldest first in each group`}
        </p>
      </div>
      <div className="filters"><ProjectChips projects={projects} /></div>
      <div className="body">
        {error && <p className="error" role="alert">{error}</p>}
        {data != null && rows.length === 0 && <p className="s none">Nothing needs you right now.</p>}
        {GROUPS.map((g) => {
          const group = rows.filter((r) => r.ask_kind === g)
          if (!group.length) return null
          return (
            <section key={g} className="ask-group">
              <h2 className="grp">{KIND_LABEL[g]} <span className="n">{group.length}</span></h2>
              {g === 'later' ? (
                <>
                  <button type="button" className="collapsed" aria-expanded={laterOpen} onClick={() => setLaterOpen(!laterOpen)}>
                    {`${laterOpen ? '▾' : '▸'} ${wide ? `${group.length} not due yet` : group.map((r) => `${r.ref} ${r.title}`).join(' · ')}`}
                  </button>
                  {laterOpen && <ul className="rows">{group.map(row)}</ul>}
                </>
              ) : (
                <ul className="rows">{group.map(row)}</ul>
              )}
            </section>
          )
        })}
      </div>
    </main>
  )
  if (!wide) return list
  return (
    <div className="split">
      <div className="l">{list}</div>
      <div className="r">{sel && <Detail row={sel} />}</div>
    </div>
  )
}
