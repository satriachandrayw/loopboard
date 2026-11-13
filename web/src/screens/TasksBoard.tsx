import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { apiGet, apiPost, AuthError } from '../api'
import ProjectChips from '../components/ProjectChips'
import TaskCard from '../components/TaskCard'
import TokenPrompt from '../components/TokenPrompt'
import ViewSwitch from '../components/ViewSwitch'
import { announceChange, nowSeconds, TASK_COLUMNS, waitKind } from '../format'
import { useProject, useProjects } from '../project'
import { useNarrow } from '../useNarrow'
import type { TaskLane, TasksBoardResponse, TaskView } from '../types'

const laneId = (lane: TaskLane) => lane.epic?.key ?? 'none'
const foldKey = (project: string) => `loopboard.lanes.${project}`

function readFolded(project: string): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(foldKey(project)) ?? '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

function LaneHead({ lane, folded, onToggle }: { lane: TaskLane; folded: boolean; onToggle: () => void }) {
  const p = lane.epic?.progress
  return (
    <div className="laneh">
      <button type="button" className="fold" aria-expanded={!folded} onClick={onToggle}>
        <span aria-hidden="true">{folded ? '▸' : '▾'}</span>
        {lane.epic ? (
          <>
            <span className="key">{lane.epic.key}</span>
            <span className="ttl">{lane.epic.title}</span>
          </>
        ) : (
          <span className="ttl">No epic</span>
        )}
      </button>
      {p ? (
        <>
          <span className="pbx" aria-hidden="true">
            <i style={{ width: p.total ? `${Math.round((100 * p.done) / p.total)}%` : '0%' }} />
          </span>
          <span className="m">{`${p.done}/${p.total}${folded ? ' · collapsed' : ''}`}</span>
        </>
      ) : (
        <span className="m">{folded ? 'small or one-off work · collapsed' : 'small or one-off work'}</span>
      )}
    </div>
  )
}

export default function TasksBoard() {
  const [project] = useProject()
  const projects = useProjects()
  const narrow = useNarrow()
  const [waiting, setWaiting] = useState('')
  const [data, setData] = useState<TasksBoardResponse | null>(null)
  const [needsAuth, setNeedsAuth] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [folded, setFolded] = useState<string[]>(() => (project ? readFolded(project) : []))
  const [tab, setTab] = useState(0)
  const seq = useRef(0)

  useEffect(() => setFolded(project ? readFolded(project) : []), [project])

  const load = useCallback(async () => {
    if (!project) return
    const n = ++seq.current
    try {
      const d = await apiGet<TasksBoardResponse>(`/api/projects/${encodeURIComponent(project)}/tasks`)
      if (n !== seq.current) return
      setData(d)
      setNeedsAuth(false)
      setError(null)
    } catch (e) {
      if (n !== seq.current) return
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError('Could not load the tasks.')
    }
  }, [project])

  useEffect(() => {
    setData(null)
    void load()
  }, [load])

  const toggle = (id: string) => {
    const next = folded.includes(id) ? folded.filter((x) => x !== id) : [...folded, id]
    setFolded(next)
    localStorage.setItem(foldKey(project), JSON.stringify(next))
  }

  const move = async (key: string, status: string) => {
    try {
      await apiPost(`/api/tasks/${encodeURIComponent(key)}/status`, { status })
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
    const from = e.dataTransfer.getData('application/x-loopboard-task')
    if (key && from && from !== target) void move(key, target)
  }

  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />

  const now = nowSeconds()
  const keep = (t: TaskView) => !waiting || waitKind(t.waiting_on) === waiting
  const lanes = data && Array.isArray(data.lanes) ? data.lanes : []
  const cell = (lane: TaskLane, col: string) => (lane.tasks[col] ?? []).filter(keep)
  const card = (t: TaskView) => (
    <TaskCard key={t.key} task={t} nowSeconds={now} draggable={Object.keys(t.links_summary).length === 0} />
  )

  return (
    <main className="screen board tasks-board">
      {narrow && <div className="top"><h1 className="t">{project ? `${project} tasks` : 'Tasks'}</h1></div>}
      <div className="filters">
        <ViewSwitch view="tasks" />
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
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!project ? (
        <section className="empty panel">
          <h1 className="t">Pick a project to see its tasks</h1>
          <p className="s">A Tasks board always shows one project, one lane per epic.</p>
        </section>
      ) : narrow ? (
        <>
          <div role="tablist" className="stabs">
            {TASK_COLUMNS.map(([c, label], i) => (
              <button key={c} type="button" role="tab" aria-selected={i === tab}
                className={i === tab ? 'on' : undefined} onClick={() => setTab(i)}>
                {`${label} ${lanes.reduce((n, l) => n + cell(l, c).length, 0)}`}
              </button>
            ))}
          </div>
          <div className="pcol">
            {lanes.map((lane) => {
              const tasks = cell(lane, TASK_COLUMNS[tab][0])
              if (!tasks.length) return null
              return (
                <section key={laneId(lane)}>
                  <h3 className="plane">{lane.epic ? `${lane.epic.key} · ${lane.epic.title}` : 'No epic'}</h3>
                  {tasks.map(card)}
                </section>
              )
            })}
          </div>
        </>
      ) : (
        <>
          <div className="colhead">
            {TASK_COLUMNS.map(([c, label]) => <div key={c}>{label}</div>)}
          </div>
          {lanes.map((lane) => {
            const id = laneId(lane)
            const shut = folded.includes(id)
            return (
              <section key={id} className={`lane${lane.epic ? '' : ' no-epic'}`}>
                <LaneHead lane={lane} folded={shut} onToggle={() => toggle(id)} />
                {!shut && (
                  <div className="lanebody">
                    {TASK_COLUMNS.map(([c]) => {
                      const tasks = cell(lane, c)
                      return (
                        <div key={c} className="column lanecol" data-column={c}
                          onDragOver={(e) => e.preventDefault()} onDrop={dropOn(c)}>
                          {tasks.length ? tasks.map(card) : <p className="empty-cell">—</p>}
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>
            )
          })}
        </>
      )}
    </main>
  )
}
