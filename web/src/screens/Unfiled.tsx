import { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, AuthError } from '../api'
import Menu from '../components/Menu'
import type { MenuItem } from '../components/Menu'
import NewTaskForm from '../components/NewTaskForm'
import ProjectChips from '../components/ProjectChips'
import TokenPrompt from '../components/TokenPrompt'
import { announceChange, ageSince, isOpenItem } from '../format'
import { useProject, useProjects, withProject } from '../project'
import { useApi } from '../useApi'
import type { TaskLane, TasksBoardResponse, UnfiledRow } from '../types'

// One write per row: link it to a task, or file it as ignored.
type Write = { path: string; body: unknown }

const OPEN_TASK = ['todo', 'in_progress', 'review']

// Open tasks of the given projects, as menu entries grouped by lane (epic, then No epic).
function useOpenTasks(projects: string[]): [Record<string, TaskLane[]>, () => void] {
  const [byProject, setByProject] = useState<Record<string, TaskLane[]>>({})
  const [tick, setTick] = useState(0)
  const wanted = [...new Set(projects)].sort().join(',')
  useEffect(() => {
    let live = true
    const keys = wanted ? wanted.split(',') : []
    void Promise.all(keys.map((p) =>
      apiGet<TasksBoardResponse>(`/api/projects/${encodeURIComponent(p)}/tasks`)
        .then((b) => [p, Array.isArray(b?.lanes) ? b.lanes : []] as const)
        .catch(() => [p, []] as const),
    )).then((pairs) => { if (live) setByProject(Object.fromEntries(pairs)) })
    return () => { live = false }
  }, [wanted, tick])
  return [byProject, () => setTick((t) => t + 1)]
}

function taskItems(lanes: TaskLane[], pick: (key: string) => void): MenuItem[] {
  return lanes.flatMap((lane) => {
    const group = lane.epic ? `${lane.epic.key} · ${lane.epic.title}` : 'No epic'
    return OPEN_TASK.flatMap((c) => lane.tasks[c] ?? [])
      .sort((a, b) => a.id - b.id)
      .map((t) => ({ label: `${t.key} · ${t.summary}`, group, onSelect: () => pick(t.key) }))
  })
}

// The one project these rows belong to: their own when they agree, else the chip's.
function projectOf(rows: UnfiledRow[], chipProject: string): string {
  const keys = new Set(rows.map((r) => r.project_key).filter((k): k is string => !!k))
  return keys.size === 1 ? [...keys][0] : keys.size === 0 ? chipProject : ''
}

interface NewTaskFor {
  ids: number[]
  project: string
  summary: string
}

interface ActionsProps {
  rows: UnfiledRow[]
  tasks: Record<string, TaskLane[]>
  chipProject: string
  busy: boolean
  run: (rows: UnfiledRow[], write: (r: UnfiledRow) => Write) => void
  newTask: (f: NewTaskFor) => void
}

// Link to task ▾ · New task from this… · Ignore, for one row or for the bulk selection.
function Actions({ rows, tasks, chipProject, busy, run, newTask }: ActionsProps) {
  const project = projectOf(rows, chipProject)
  const items = taskItems(tasks[project] ?? [], (key) =>
    run(rows, (r) => ({ path: `/api/items/${r.id}/link`, body: { task_key: key } })))
  return (
    <div className="btns">
      <Menu label="Link to task ▾" disabled={busy || items.length === 0} items={items} />
      <button type="button" className="btn g" disabled={busy}
        onClick={() => newTask({ ids: rows.map((r) => r.id), project, summary: rows[0].title })}>
        {rows.length === 1 ? 'New task from this…' : 'New task from these…'}
      </button>
      <button type="button" className="btn g" disabled={busy}
        onClick={() => run(rows, (r) => ({ path: `/api/items/${r.id}/filing`, body: { filing: 'ignored' } }))}>
        Ignore
      </button>
    </div>
  )
}

export default function Unfiled() {
  const [project] = useProject()
  const projects = useProjects()
  const { data, setData, needsAuth, setNeedsAuth, error, setError, load } =
    useApi<UnfiledRow[]>(withProject('/api/unfiled', project), 'Could not load.')
  const [showDone, setShowDone] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [progress, setProgress] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newTaskFor, setNewTaskFor] = useState<NewTaskFor | null>(null)

  const all = useMemo(() => (Array.isArray(data) ? data : []), [data])
  const openRows = all.filter(isOpenItem)
  const doneCount = all.length - openRows.length
  const shown = showDone ? all : openRows
  const picked = shown.filter((r) => selected.has(r.id))
  const [tasks, reloadTasks] = useOpenTasks(
    [...shown.map((r) => r.project_key ?? project), project].filter((k): k is string => !!k))

  // Sequential, so the count is honest; the first failure stops the run and is shown.
  const run = async (rows: UnfiledRow[], write: (r: UnfiledRow) => Write) => {
    setBusy(true)
    setError(null)
    const filed: number[] = []
    const many = rows.length > 1
    if (many) setProgress(`Filed 0/${rows.length}`)
    try {
      for (const r of rows) {
        try {
          const w = write(r)
          await apiPost(w.path, w.body)
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
  const actionProps = { tasks, chipProject: project, busy, newTask: setNewTaskFor,
    run: (rows: UnfiledRow[], write: (r: UnfiledRow) => Write) => void run(rows, write) }

  return (
    <main className="screen list">
      <div className="top">
        <h1 className="t">Unfiled</h1>
        <p className="s">{`Found by connectors, not yet linked to a task · ${openRows.length} open`}</p>
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
      {newTaskFor && (
        <NewTaskForm
          projects={projects}
          initialProject={newTaskFor.project}
          initialSummary={newTaskFor.summary}
          itemId={newTaskFor.ids[0]}
          onCancel={() => setNewTaskFor(null)}
          onCreated={async (key) => {
            const [first, ...rest] = newTaskFor.ids
            setNewTaskFor(null)
            setData((d) => (Array.isArray(d) ? d.filter((r) => r.id !== first) : d))
            setSelected((s) => new Set([...s].filter((id) => id !== first)))
            announceChange()
            const others = new Set(rest)
            if (others.size)
              await run(all.filter((r) => others.has(r.id)), (r) => ({ path: `/api/items/${r.id}/link`, body: { task_key: key } }))
            reloadTasks()
          }}
        />
      )}
    </main>
  )
}
