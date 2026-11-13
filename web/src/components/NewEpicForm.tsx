import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost, AuthError } from '../api'
import type { Project } from '../types'

const STAGES = ['idea', 'spec', 'plan', 'build', 'review', 'ship']

interface Props {
  projects: Project[] | null
  initialProject?: string
  initialTitle?: string
  onCreated: (key: string) => void | Promise<void>
  onCancel: () => void
}

// The signed-in Access user is `name@domain`; a token principal has no '@' and falls back to owner.
const localPart = (principal: unknown) =>
  typeof principal === 'string' && principal.includes('@') ? principal.split('@')[0] : 'owner'

export default function NewEpicForm({ projects, initialProject = '', initialTitle = '', onCreated, onCancel }: Props) {
  const [title, setTitle] = useState(initialTitle)
  const [project, setProject] = useState(initialProject)
  const [stage, setStage] = useState('idea')
  const [kind, setKind] = useState<'human' | 'agent'>('human')
  const [name, setName] = useState('owner')
  const [goal, setGoal] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nameTouched = useRef(false)

  useEffect(() => {
    let live = true
    apiGet<{ principal?: string }>('/api/health')
      .then((h) => { if (live && !nameTouched.current) setName(localPart(h?.principal)) })
      .catch(() => {})
    return () => { live = false }
  }, [])

  const submit = async () => {
    if (!title.trim()) return setError('A title is required.')
    if (!project) return setError('Choose a project.')
    if (!name.trim()) return setError('Say who it waits on.')
    if (!goal.trim()) return setError('Add a description: what this epic is for.')
    const body = { title: title.trim(), stage, waiting_on: `${kind}:${name.trim()}`, goal: goal.trim() }
    setBusy(true)
    setError(null)
    try {
      const epic = await apiPost<{ key: string }>(`/api/projects/${encodeURIComponent(project)}/epics`, body)
      await onCreated(epic.key)
    } catch (e) {
      setError(e instanceof AuthError ? 'Not signed in: reload and sign in again.' : 'Could not create the epic.')
      setBusy(false)
    }
  }

  return (
    <div className="overlay">
      <div className="panel dialog" role="dialog" aria-modal="true" aria-labelledby="new-epic-h">
        <h1 id="new-epic-h" className="t">New epic</h1>
        <form noValidate onSubmit={(e) => { e.preventDefault(); void submit() }}>
          <label className="field">
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required autoFocus />
          </label>
          <label className="field">
            <span>Project</span>
            <select value={project} onChange={(e) => setProject(e.target.value)} required>
              <option value="">Choose a project…</option>
              {(projects ?? []).map((p) => (
                <option key={p.key} value={p.key}>{p.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Stage</span>
            <select value={stage} onChange={(e) => setStage(e.target.value)}>
              {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <div className="field">
            <span>Waiting on</span>
            <div className="pair">
              <select aria-label="Waiting on kind" value={kind} onChange={(e) => setKind(e.target.value as 'human' | 'agent')}>
                <option value="human">human:</option>
                <option value="agent">agent:</option>
              </select>
              <input aria-label="Waiting on name" value={name}
                onChange={(e) => { nameTouched.current = true; setName(e.target.value) }} />
            </div>
          </div>
          <label className="field">
            <span>Description</span>
            <textarea rows={3} value={goal} onChange={(e) => setGoal(e.target.value)} />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="btns">
            <button type="submit" className="btn" disabled={busy}>Create</button>
            <button type="button" className="btn g" onClick={onCancel}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  )
}
