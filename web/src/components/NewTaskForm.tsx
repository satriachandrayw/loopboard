import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { apiGet, apiPost, AuthError } from '../api'
import { localPart } from './NewEpicForm'
import type { BoardResponse, Card, Project } from '../types'

const REF = /^[A-Z][A-Z0-9]{1,9}-[0-9]+$/

interface Props {
  projects: Project[] | null
  initialProject?: string
  initialEpic?: string
  initialSummary?: string
  itemId?: number
  onCreated: (key: string) => void | Promise<void>
  onCancel: () => void
}

// Open epics (every board column but Done), for the Epic picker.
function useOpenEpics(): Card[] {
  const [epics, setEpics] = useState<Card[]>([])
  useEffect(() => {
    let live = true
    apiGet<BoardResponse>('/api/board')
      .then((b) => {
        if (live && Array.isArray(b?.columns))
          setEpics(b.columns.filter((c) => c.column !== 'done').flatMap((c) => c.cards))
      })
      .catch(() => {})
    return () => { live = false }
  }, [])
  return epics
}

const Req = ({ children, note }: { children: ReactNode; note?: string }) => (
  <span>{children} <i className="req" aria-hidden="true">*</i>{note && <em>{` ${note}`}</em>}</span>
)

export default function NewTaskForm({ projects, initialProject = '', initialEpic = '', initialSummary = '', itemId, onCreated, onCancel }: Props) {
  const epics = useOpenEpics()
  const [project, setProject] = useState(initialProject)
  const [type, setType] = useState<'task' | 'bug'>('task')
  const [summary, setSummary] = useState(initialSummary)
  const [description, setDescription] = useState('')
  const [doneWhen, setDoneWhen] = useState('')
  const [epic, setEpic] = useState(initialEpic)
  const [priority, setPriority] = useState('medium')
  const [owner, setOwner] = useState('owner')
  const [kind, setKind] = useState<'human' | 'agent'>('human')
  const [name, setName] = useState('owner')
  const [refs, setRefs] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const touched = useRef({ owner: false, name: false })

  useEffect(() => {
    let live = true
    apiGet<{ principal?: string }>('/api/health')
      .then((h) => {
        if (!live) return
        const me = localPart(h?.principal)
        if (!touched.current.owner) setOwner(me)
        if (!touched.current.name) setName(me)
      })
      .catch(() => {})
    return () => { live = false }
  }, [])

  const mine = epics.filter((e) => e.project_key === project)
  const pickProject = (p: string) => {
    setProject(p)
    if (!epics.some((e) => e.key === epic && e.project_key === p)) setEpic('')
  }

  const submit = async () => {
    const refList = refs.split(/[\s,]+/).filter(Boolean)
    if (!project) return setError('Choose a project.')
    if (!summary.trim()) return setError('A summary is required.')
    if (!description.trim()) return setError('Add a description: what this task is.')
    if (!doneWhen.trim()) return setError('Add a "Done when" line.')
    if (!owner.trim()) return setError('Say who owns it.')
    if (!name.trim()) return setError('Say who it waits on.')
    if (!refList.every((r) => REF.test(r))) return setError('Refs look like ABC-123.')
    const body = {
      summary: summary.trim(), description: description.trim(), done_when: doneWhen.trim(), owner: owner.trim(),
      waiting_on: `${kind}:${name.trim()}`, type, priority, epic_key: epic || null, refs: refList,
      ...(itemId !== undefined ? { item_id: itemId } : {}),
    }
    setBusy(true)
    setError(null)
    try {
      const task = await apiPost<{ key: string }>(`/api/projects/${encodeURIComponent(project)}/tasks`, body)
      await onCreated(task.key)
    } catch (e) {
      setError(e instanceof AuthError ? 'Not signed in: reload and sign in again.' : 'Could not create the task.')
      setBusy(false)
    }
  }

  return (
    <div className="overlay">
      <div className="panel dialog wide" role="dialog" aria-modal="true" aria-labelledby="new-task-h">
        <h1 id="new-task-h" className="t">New task</h1>
        <form noValidate onSubmit={(e) => { e.preventDefault(); void submit() }}>
          <div className="two">
            <label className="field">
              <Req>Project</Req>
              <select value={project} onChange={(e) => pickProject(e.target.value)} required>
                <option value="">Choose a project…</option>
                {(projects ?? []).map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
              </select>
            </label>
            <label className="field">
              <Req>Type</Req>
              <select value={type} onChange={(e) => setType(e.target.value as 'task' | 'bug')}>
                <option value="task">Task</option>
                <option value="bug">Bug</option>
              </select>
            </label>
          </div>
          <label className="field">
            <Req>Summary</Req>
            <input value={summary} maxLength={300} onChange={(e) => setSummary(e.target.value)} required autoFocus />
          </label>
          <label className="field">
            <Req note="(what this task is)">Description</Req>
            <textarea rows={3} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className="field">
            <Req>Done when</Req>
            <input value={doneWhen} maxLength={300} onChange={(e) => setDoneWhen(e.target.value)} />
          </label>
          <div className="two">
            <label className="field">
              <span>Epic (parent)</span>
              <select value={epic} onChange={(e) => setEpic(e.target.value)}>
                <option value="">No epic</option>
                {mine.map((e) => <option key={e.key} value={e.key}>{`${e.key} · ${e.title}`}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Priority</span>
              <select value={priority} onChange={(e) => setPriority(e.target.value)}>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
          </div>
          <div className="two">
            <label className="field">
              <Req>Owner</Req>
              <input value={owner} maxLength={100}
                onChange={(e) => { touched.current.owner = true; setOwner(e.target.value) }} />
            </label>
            <div className="field">
              <Req>Waiting on</Req>
              <div className="pair">
                <select aria-label="Waiting on kind" value={kind} onChange={(e) => setKind(e.target.value as 'human' | 'agent')}>
                  <option value="human">human:</option>
                  <option value="agent">agent:</option>
                </select>
                <input aria-label="Waiting on name" value={name}
                  onChange={(e) => { touched.current.name = true; setName(e.target.value) }} />
              </div>
            </div>
          </div>
          <label className="field">
            <span>Refs (other keys that mean this task)</span>
            <input value={refs} placeholder="ABC-123, ABC-124" onChange={(e) => setRefs(e.target.value)} />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="btns">
            <button type="submit" className="btn" disabled={busy}>Create task</button>
            <button type="button" className="btn g" onClick={onCancel}>Cancel</button>
          </div>
          <p className="note">
            Reporter and created time are filled in by Loopboard. Status starts at Todo. Put the new key in square
            brackets at the start of a card or PR title and the sync links it here; a title carrying a ref links too.
          </p>
        </form>
      </div>
    </div>
  )
}
