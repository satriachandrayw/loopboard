import TokenPrompt from '../components/TokenPrompt'
import { useApi } from '../useApi'
import type { NeedsYouRow } from '../types'

export default function NeedsYou() {
  const { data, needsAuth, error, load } = useApi<NeedsYouRow[]>('/api/needs-you', 'Could not load.')
  if (needsAuth) return <TokenPrompt onSaved={() => void load()} />
  return (
    <main className="list">
      <h2>Needs you</h2>
      {error && <p className="error" role="alert">{error}</p>}
      <ul>
        {(data ?? []).map((r) => (
          <li key={`${r.kind}:${r.id}`}>
            {r.kind === 'epic' ? (
              <a href={`#/epic/${encodeURIComponent(r.ref)}`}>{r.title}</a>
            ) : r.url ? (
              <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
            ) : (
              <span>{r.title}</span>
            )}
            <span className="reasons">{r.reasons.join(' · ')}</span>
          </li>
        ))}
      </ul>
    </main>
  )
}
