import { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, AuthError } from '../api'
import Menu from '../components/Menu'
import type { MenuItem } from '../components/Menu'
import NewEpicForm from '../components/NewEpicForm'
import ProjectChips from '../components/ProjectChips'
import TokenPrompt from '../components/TokenPrompt'
import { announceChange, ageSince, isOpenItem } from '../format'
import { useProject, useProjects, withProject } from '../project'
import { useApi } from '../useApi'
import type { BoardResponse, Card, Project, UnfiledRow } from '../types'

type Filing = { filing: 'epic'; epic_key: string } | { filing: 'standalone'; project_key: string } | { filing: 'ignored' }

interface NewEpicFor {
  ids: number[]
  project: string
  title: string
}

// Open epics (every board column but Done) to file into.
function useOpenEpics(): [Card[], () => void] {
  const [epics, setEpics] = useState<Card[]>([])
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    apiGet<BoardResponse>('/api/board')
      .then((b) => {
        if (live && Array.isArray(b?.columns))
          setEpics(b.columns.filter((c) => c.column !== 'done').flatMap((c) => c.cards))
      })
      .catch(() => {})
    return () => { live = false }
  }, [tick])
  return [epics, () => setTick((t) => t + 1)]
}

// Epics of the given project when it has any, else every open epic.
function epicsFor(epics: Card[], project: string | null): Card[] {
  const mine = project ? epics.filter((e) => e.project_key === project) : []
  return mine.length > 0 ? mine : epics
}

const sharedProject = (rows: UnfiledRow[]) => {
  const keys = new Set(rows.map((r) => r.project_key))
  return keys.size === 1 ? [...keys][0] : null
}

interface ActionsProps {
  rows: UnfiledRow[]
  epics: Card[]
  projects: Project[] | null
  chipProject: string
  busy: boolean
  run: (rows: UnfiledRow[], body: (r: UnfiledRow) => Filing) => void
  newEpic: (f: NewEpicFor) => void
}

// File to epic ▾ · Standalone · Ignore, for one row or for the bulk selection.
function Actions({ rows, epics, projects, chipProject, busy, run, newEpic }: ActionsProps) {
  const shared = sharedProject(rows)
  const fileItems: MenuItem[] = [
    ...epicsFor(epics, shared).map((e) => ({
      label: `${e.key} · ${e.title}`,
      onSelect: () => run(rows, () => ({ filing: 'epic', epic_key: e.key })),
    })),
    {
      label: '+ New epic…',
      onSelect: () => newEpic({ ids: rows.map((r) => r.id), project: shared ?? chipProject, title: rows.length === 1 ? rows[0].title : '' }),
    },
  ]
  const projectOf = (r: UnfiledRow) => r.project_key || chipProject
  const allKnown = rows.every((r) => projectOf(r))
  return (
    <div className="btns">
      <Menu label="File to epic ▾" items={fileItems} disabled={busy} />
      {allKnown ? (
        <button type="button" className="btn g" disabled={busy}
          onClick={() => run(rows, (r) => ({ filing: 'standalone', project_key: projectOf(r) }))}>
          Standalone
        </button>
      ) : (
        <Menu label="Standalone ▾" className="btn g" disabled={busy}
          items={(projects ?? []).map((p) => ({
            label: p.name,
            onSelect: () => run(rows, (r) => ({ filing: 'standalone', project_key: projectOf(r) || p.key })),
          }))} />
      )}
      <button type="button" className="btn g" disabled={busy} onClick={() => run(rows, () => ({ filing: 'ignored' }))}>
        Ignore
      </button>
    </div>
  )
}

export default function Unfiled() {
  const [project] = useProject()
  const projects = useProjects()
  const [epics, reloadEpics] = useOpenEpics()
  const { data, setData, needsAuth, setNeedsAuth, error, setError, load } =
    useApi<UnfiledRow[]>(withProject('/api/unfiled', project), 'Could not load.')
  const [showDone, setShowDone] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [progress, setProgress] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newEpicFor, setNewEpicFor] = useState<NewEpicFor | null>(null)

  const all = useMemo(() => (Array.isArray(data) ? data : []), [data])
  const openRows = all.filter(isOpenItem)
  const doneCount = all.length - openRows.length
  const shown = showDone ? all : openRows
  const picked = shown.filter((r) => selected.has(r.id))

  // Sequential, so the count is honest; the first failure stops the run and is shown.
  const run = async (rows: UnfiledRow[], body: (r: UnfiledRow) => Filing) => {
    setBusy(true)
    setError(null)
    const filed: number[] = []
    const many = rows.length > 1
    if (many) setProgress(`Filed 0/${rows.length}`)
    try {
      for (const r of rows) {
        try {
          await apiPost(`/api/items/${r.id}/filing`, body(r))
        } catch (e) {
          if (e instanceof AuthError) setNeedsAuth(true)
          else setError(`Filing "${r.title}" failed; stopped after ${filed.length} of ${rows.length}.`)
          return
        }
        filed.push(r.id)
        if (many) setProgress(`Filed ${filed.length}/${rows.length}`)
      }
    } finally {
      const gone = new Set(filed)
      setData((d) => (Array.isArray(d) ? d.filter((r) => !gone.has(r.id)) : d))
      setSelected((s) => new Set([...s].filter((id) => !gone.has(id))))
      setBusy(false)
      if (filed.length) announceChange()
    }
  }

  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const allPicked = shown.length > 0 && picked.length === shown.length
  const actionProps = { epics, projects, chipProject: project, busy, newEpic: setNewEpicFor,
    run: (rows: UnfiledRow[], body: (r: UnfiledRow) => Filing) => void run(rows, body) }

  return (
    <main className="screen list">
      <div className="top">
        <h1 className="t">Unfiled</h1>
        <p className="s">{`Found by connectors, not yet in an epic · ${openRows.length} open`}</p>
      </div>
      <div className="filters">
        <ProjectChips projects={projects} />
        <button type="button" className={`chip${showDone ? ' on' : ''}`} aria-pressed={showDone}
          onClick={() => setShowDone(!showDone)}>
          {`Show done (${doneCount})`}
        </button>
      </div>
      <div className="body">
        {error && <p className="error" role="alert">{error}</p>}
        {progress && <p className="progress" role="status">{progress}</p>}
        {shown.length > 0 && (
          <div className="bulk">
            <label className="check">
              <input type="checkbox" checked={allPicked}
                onChange={() => setSelected(allPicked ? new Set() : new Set(shown.map((r) => r.id)))} />
              <span>Select all shown</span>
            </label>
            {picked.length > 0 && (
              <div className="bulk-actions" role="toolbar" aria-label="Bulk actions">
                <span className="meta">{`${picked.length} selected`}</span>
                <Actions rows={picked} {...actionProps} />
              </div>
            )}
          </div>
        )}
        {data != null && shown.length === 0 && <p className="s none">Nothing to file.</p>}
        <ul className="rows">
          {shown.map((r) => (
            <li key={r.id} className={`card urow${isOpenItem(r) ? '' : ' done'}`}>
              <div className="h">
                <input type="checkbox" aria-label={`Select ${r.title}`} checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                <span className="ti">{r.title}</span>
                {r.url && <a className="ext" href={r.url} target="_blank" rel="noreferrer">open ↗</a>}
              </div>
              <div className="meta">
                <span className="src">{r.source}</span>
                {` ${r.external_id} · ${r.category.replaceAll('_', ' ')} · ${ageSince(r.last_activity_at) ?? ''}`}
                {r.project_key && <span className="proj">{r.project_key}</span>}
              </div>
              <Actions rows={[r]} {...actionProps} />
            </li>
          ))}
        </ul>
      </div>
      {newEpicFor && (
        <NewEpicForm
          projects={projects}
          initialProject={newEpicFor.project}
          initialTitle={newEpicFor.title}
          onCancel={() => setNewEpicFor(null)}
          onCreated={async (key) => {
            const ids = new Set(newEpicFor.ids)
            setNewEpicFor(null)
            reloadEpics()
            await run(all.filter((r) => ids.has(r.id)), () => ({ filing: 'epic', epic_key: key }))
          }}
        />
      )}
    </main>
  )
}
