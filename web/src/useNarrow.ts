import { useEffect, useState } from 'react'

const NARROW = '(max-width: 640px)'

const mq = () => (typeof window.matchMedia === 'function' ? window.matchMedia(NARROW) : null)

// Phone layout: one board column at a time and the bottom tab bar.
export function useNarrow(): boolean {
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
