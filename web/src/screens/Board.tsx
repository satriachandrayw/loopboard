import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { apiGet, apiPatch, AuthError } from '../api'
import Column from '../components/Column'
import NewEpicForm from '../components/NewEpicForm'
import ProjectChips from '../components/ProjectChips'
import TokenPrompt from '../components/TokenPrompt'
import ViewSwitch from '../components/ViewSwitch'
import { announceChange, epicHref, isOpenItem, nowSeconds } from '../format'
import { useProject, useProjects, withProject } from '../project'
import { useNarrow } from '../useNarrow'
import type { BoardResponse, UnfiledRow } from '../types'

function EmptyBoard({ project, onNew }: { project: string; onNew: () => void }) {
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => {
    let live = true
    apiGet<UnfiledRow[]>(withProject('/api/unfiled', project))
      .then((rows) => { if (live && Array.isArray(rows)) setOpen(rows.filter(isOpenItem).length) })
      .catch(() => {})
    return () => { live = false }
  }, [project])
  return (
    <section className="empty panel">
      <h1 className="t">No epics yet</h1>
      <p className="s">
        {open == null ? 'Counting unfiled items…' : `${open} open unfiled ${open === 1 ? 'item' : 'items'} waiting to be filed.`}
      </p>
      <div className="btns">
        <a className="btn" href="#/unfiled">File them →</a>
        <button type="button" className="btn g" onClick={onNew}>+ New epic</button>
      </div>
    </section>
  )
}

export default function Board() {
  const [project] = useProject()
  const projects = useProjects()
  const [waiting, setWaiting] = useState('')
  const [data, setData] = useState<BoardResponse | null>(null)
  const [needsAuth, setNeedsAuth] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(0)
  const [creating, setCreating] = useState(false)
  const narrow = useNarrow()
  // Only the newest request may set state.
  const seq = useRef(0)

  const load = useCallback(async () => {
    const q = new URLSearchParams()
    if (project) q.set('project', project)
    if (waiting) q.set('waiting_on', waiting)
    const qs = q.toString()
    const n = ++seq.current
    try {
      const d = await apiGet<BoardResponse>('/api/board' + (qs ? `?${qs}` : ''))
      if (n !== seq.current) return
      setData(d)
      setNeedsAuth(false)
      setError(null)
    } catch (e) {
      if (n !== seq.current) return
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError('Could not load the board.')
    }
  }, [project, waiting])

  useEffect(() => {
    void load()
  }, [load])

  const move = async (key: string, column: string) => {
    try {
      await apiPatch(`/api/epics/${encodeURIComponent(key)}`, { manual_column: column })
      await load()
      announceChange()
    } catch (e) {
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError('Move failed.')
    }
  }

  const dropOn = (target: string) => (e: DragEvent<HTMLElement>) => {
    e.preventDefault()
    const key = e.dataTransfer.getData('text/plain')
    const from = e.dataTransfer.getData('application/x-loopboard-column')
    if (key && from === 'backlog' && target === 'todo') void move(key, 'todo')
  }

  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />

  const now = nowSeconds()
  const cols = Array.isArray(data?.columns) ? data.columns : []
  const empty = data != null && !waiting && cols.every((c) => c.count === 0)
  const shown = narrow ? cols.slice(tab, tab + 1) : cols

  return (
    <main className="screen board">
      {narrow && <div className="top"><h1 className="t">Board</h1></div>}
      <div className="filters">
        <ViewSwitch view="epics" />
        <ProjectChips projects={projects} />
        <label className="chip select">
          <span>Waiting on:</span>
          <select aria-label="Waiting on" value={waiting} onChange={(e) => setWaiting(e.target.value)}>
            <option value="">anyone</option>
            <option value="human">you</option>
            <option value="agent">an agent</option>
            <option value="source">a source</option>
          </select>
        </label>
        <button type="button" className="btn" onClick={() => setCreating(true)}>+ New epic</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {empty ? (
        <EmptyBoard project={project} onNew={() => setCreating(true)} />
      ) : (
        <>
          {narrow && (
            <div role="tablist" className="stabs">
              {cols.map((c, i) => (
                <button key={c.column} type="button" role="tab" aria-selected={i === tab}
                  className={i === tab ? 'on' : undefined} onClick={() => setTab(i)}>
                  {`${c.label} ${c.count}`}
                </button>
              ))}
            </div>
          )}
          <div className="columns">
            {shown.map((c) => (
              <Column key={c.column} data={c} nowSeconds={now} onMove={move} onDropCard={dropOn(c.column)} />
            ))}
          </div>
        </>
      )}
      {creating && (
        <NewEpicForm
          projects={projects}
          initialProject={project}
          onCancel={() => setCreating(false)}
          onCreated={(key) => {
            setCreating(false)
            announceChange()
            window.location.hash = epicHref(key)
          }}
        />
      )}
    </main>
  )
}
