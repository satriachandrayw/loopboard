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

const WIDE = '(min-width: 1100px)'

// Desktop split (Needs you list + detail) from 1100 px.
export function useWide(): boolean {
  const q = () => (typeof window.matchMedia === 'function' ? window.matchMedia(WIDE) : null)
  const [wide, setWide] = useState(() => q()?.matches ?? false)
  useEffect(() => {
    const m = q()
    if (!m) return
    const h = () => setWide(m.matches)
    m.addEventListener?.('change', h)
    return () => m.removeEventListener?.('change', h)
  }, [])
  return wide
}
