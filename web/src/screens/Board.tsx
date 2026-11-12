import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { apiGet, apiPatch, AuthError } from '../api'
import Column from '../components/Column'
import TokenPrompt from '../components/TokenPrompt'
import type { BoardResponse } from '../types'

const NARROW = '(max-width: 640px)'
const DEBOUNCE_MS = 300

function useNarrow(): boolean {
  const mq = () => (typeof window.matchMedia === 'function' ? window.matchMedia(NARROW) : null)
  const [narrow, setNarrow] = useState(() => mq()?.matches ?? false)
  useEffect(() => {
    const m = mq()
    if (!m) return
    const h = () => setNarrow(m.matches)
    m.addEventListener?.('change', h)
    return () => m.removeEventListener?.('change', h)
  }, [])
  return narrow
}

export default function Board() {
  const [project, setProject] = useState('')
  const [waiting, setWaiting] = useState('')
  const [data, setData] = useState<BoardResponse | null>(null)
  const [needsAuth, setNeedsAuth] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(0)
  const narrow = useNarrow()
  // The project text filter is debounced; only the newest request may set state.
  const [projectQ, setProjectQ] = useState('')
  const seq = useRef(0)

  useEffect(() => {
    const t = setTimeout(() => setProjectQ(project.trim()), DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [project])

  const load = useCallback(async () => {
    const q = new URLSearchParams()
    if (projectQ) q.set('project', projectQ)
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
  }, [projectQ, waiting])

  useEffect(() => {
    void load()
  }, [load])

  const move = async (key: string, column: string) => {
    try {
      await apiPatch(`/api/epics/${key}`, { manual_column: column })
      await load()
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

  const nowSeconds = Math.floor(Date.now() / 1000)
  const cols = data?.columns ?? []
  const shown = narrow ? cols.slice(tab, tab + 1) : cols

  return (
    <main className="board">
      <div className="filters">
        <label>
          Project
          <input value={project} onChange={(e) => setProject(e.target.value)} />
        </label>
        <label>
          Waiting on
          <select value={waiting} onChange={(e) => setWaiting(e.target.value)}>
            <option value="">any</option>
            <option value="agent">agent</option>
            <option value="human">human</option>
            <option value="source">source</option>
          </select>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {narrow && (
        <div role="tablist" className="tabs">
          {cols.map((c, i) => (
            <button key={c.column} role="tab" aria-selected={i === tab} onClick={() => setTab(i)}>
              {c.label}
            </button>
          ))}
        </div>
      )}
      <div className="columns">
        {shown.map((c) => (
          <Column key={c.column} data={c} nowSeconds={nowSeconds} onMove={move} onDropCard={dropOn(c.column)} />
        ))}
      </div>
    </main>
  )
}
