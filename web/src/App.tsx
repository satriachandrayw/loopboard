import { useEffect, useState } from 'react'
import { apiGet } from './api'
import { isOpenItem, REFRESH_EVENT } from './format'
import { useProject, withProject } from './project'
import Board from './screens/Board'
import EpicDetail from './screens/EpicDetail'
import NeedsYou from './screens/NeedsYou'
import Stalled from './screens/Stalled'
import TaskDetail from './screens/TaskDetail'
import TasksBoard from './screens/TasksBoard'
import Unfiled from './screens/Unfiled'
import { useNarrow } from './useNarrow'
import type { NeedsYouRow, UnfiledRow } from './types'

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const h = () => setHash(window.location.hash)
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  return hash
}

interface Badges {
  needs: number | null
  unfiled: number | null
}

// Nav badges: Needs you rows and open Unfiled items, for the chosen project.
function useBadges(hash: string): Badges {
  const [project] = useProject()
  const [badges, setBadges] = useState<Badges>({ needs: null, unfiled: null })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const h = () => setTick((t) => t + 1)
    window.addEventListener(REFRESH_EVENT, h)
    return () => window.removeEventListener(REFRESH_EVENT, h)
  }, [])
  useEffect(() => {
    let live = true
    const count = async <T,>(path: string, keep: (r: T) => boolean) => {
      try {
        const rows = await apiGet<T[]>(withProject(path, project))
        return Array.isArray(rows) ? rows.filter(keep).length : null
      } catch {
        return null // auth or network: the screen itself reports it
      }
    }
    void Promise.all([count<NeedsYouRow>('/api/needs-you', () => true), count<UnfiledRow>('/api/unfiled', isOpenItem)])
      .then(([needs, unfiled]) => { if (live) setBadges({ needs, unfiled }) })
    return () => { live = false }
  }, [project, hash, tick])
  return badges
}

const NAV = [
  { href: '#/needs-you', label: 'Needs you', icon: '🙋', badge: 'needs' as const },
  { href: '#/stalled', label: 'Stalled', icon: '⏳' },
  { href: '#/board', label: 'Board', icon: '▦' },
  { href: '#/unfiled', label: 'Unfiled', icon: '📥', badge: 'unfiled' as const },
]

function current(hash: string): string {
  const hit = NAV.find((n) => n.href === hash)
  return hit ? hit.href : hash.startsWith('#/epic/') || hash.startsWith('#/task/') ? '' : '#/board'
}

// The key after `#/epic/` or `#/task/`; a malformed escape gives null (fall back to the board).
function hashKey(hash: string, at: number): string | null {
  try {
    return decodeURIComponent(hash.slice(at))
  } catch {
    return null
  }
}

export default function App() {
  const hash = useHash()
  const narrow = useNarrow()
  const badges = useBadges(hash)
  const on = current(hash)
  let screen
  if (hash === '#/needs-you') screen = <NeedsYou />
  else if (hash === '#/stalled') screen = <Stalled />
  else if (hash === '#/unfiled') screen = <Unfiled />
  else if (hash === '#/tasks') screen = <TasksBoard />
  else if (hash.startsWith('#/epic/') && hash.length > 7) {
    const key = hashKey(hash, 7)
    screen = key ? <EpicDetail key={key} epicKey={key} /> : <Board />
  } else if (hash.startsWith('#/task/') && hash.length > 7) {
    const key = hashKey(hash, 7)
    screen = key ? <TaskDetail key={key} taskKey={key} /> : <Board />
  } else screen = <Board />
  const badge = (n: (typeof NAV)[number]) => {
    const v = n.badge ? badges[n.badge] : null
    return v ? <span className="nb">{v}</span> : null
  }
  return (
    <div className={`app${narrow ? ' narrow' : ''}`}>
      <header className="bar">
        <a className="logo" href="#/board">◎ loopboard</a>
        {!narrow && (
          <nav className="nav" aria-label="Main">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} className={on === n.href ? 'on' : undefined}
                aria-current={on === n.href ? 'page' : undefined}>
                {n.label}
                {badge(n)}
              </a>
            ))}
          </nav>
        )}
      </header>
      {screen}
      {narrow && (
        <nav className="tabs" aria-label="Tabs">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className={`tab${on === n.href ? ' on' : ''}`}
              aria-current={on === n.href ? 'page' : undefined}>
              <b aria-hidden="true">{n.icon}</b>
              {n.label}
              {badge(n)}
            </a>
          ))}
        </nav>
      )}
    </div>
  )
}
