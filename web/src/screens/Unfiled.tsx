import { useState } from 'react'
import { apiPost, AuthError } from '../api'
import TokenPrompt from '../components/TokenPrompt'
import { useApi } from '../useApi'
import type { UnfiledRow } from '../types'

function Row({ row, onFile }: { row: UnfiledRow; onFile: (id: number, body: unknown) => void }) {
  const [epic, setEpic] = useState('')
  const [project, setProject] = useState('')
  return (
    <li>
      {row.url ? <a href={row.url} target="_blank" rel="noreferrer">{row.title}</a> : <span>{row.title}</span>}
      <span className="source">{`${row.source}:${row.external_id}`}</span>
      <input aria-label={`Epic key for ${row.title}`} value={epic} onChange={(e) => setEpic(e.target.value)} />
      <button type="button" disabled={!epic.trim()} onClick={() => onFile(row.id, { filing: 'epic', epic_key: epic.trim() })}>
        File to epic
      </button>
      <input aria-label={`Project key for ${row.title}`} value={project} onChange={(e) => setProject(e.target.value)} />
      <button type="button" disabled={!project.trim()} onClick={() => onFile(row.id, { filing: 'standalone', project_key: project.trim() })}>
        Standalone
      </button>
      <button type="button" onClick={() => onFile(row.id, { filing: 'ignored' })}>Ignore</button>
    </li>
  )
}

export default function Unfiled() {
  const { data, setData, needsAuth, setNeedsAuth, error, setError, load } = useApi<UnfiledRow[]>('/api/unfiled', 'Could not load.')
  const file = async (id: number, body: unknown) => {
    try {
      await apiPost(`/api/items/${id}/filing`, body)
      setData((d) => d && d.filter((r) => r.id !== id))
      setError(null)
    } catch (e) {
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError('Filing failed.')
    }
  }
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  return (
    <main className="list">
      <h2>Unfiled</h2>
      {error && <p className="error" role="alert">{error}</p>}
      <ul>
        {(data ?? []).map((r) => (
          <Row key={r.id} row={r} onFile={(id, b) => void file(id, b)} />
        ))}
      </ul>
    </main>
  )
}
