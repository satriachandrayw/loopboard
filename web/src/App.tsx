import { useEffect, useState } from 'react'
import Board from './screens/Board'
import EpicDetail from './screens/EpicDetail'
import NeedsYou from './screens/NeedsYou'
import Stalled from './screens/Stalled'
import Unfiled from './screens/Unfiled'

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const h = () => setHash(window.location.hash)
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  return hash
}

export default function App() {
  const hash = useHash()
  let screen
  if (hash === '#/needs-you') screen = <NeedsYou />
  else if (hash === '#/stalled') screen = <Stalled />
  else if (hash === '#/unfiled') screen = <Unfiled />
  else if (hash.startsWith('#/epic/') && hash.length > 7) {
    const key = decodeURIComponent(hash.slice(7))
    screen = <EpicDetail key={key} epicKey={key} />
  } else screen = <Board />
  return (
    <>
      <nav>
        <a href="#/board">Board</a>
        <a href="#/needs-you">Needs you</a>
        <a href="#/stalled">Stalled</a>
        <a href="#/unfiled">Unfiled</a>
      </nav>
      {screen}
    </>
  )
}
