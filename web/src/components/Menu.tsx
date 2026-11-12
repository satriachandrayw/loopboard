import { useEffect, useRef, useState } from 'react'

export interface MenuItem {
  label: string
  onSelect: () => void
}

interface Props {
  label: string
  items: MenuItem[]
  className?: string
  disabled?: boolean
}

// A button that opens a short list of actions; closes on choice, outside click or Escape.
export default function Menu({ label, items, className = 'btn', disabled }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  return (
    <div className="menu" ref={ref}>
      <button type="button" className={className} aria-haspopup="menu" aria-expanded={open} disabled={disabled}
        onClick={() => setOpen(!open)}>
        {label}
      </button>
      {open && (
        <ul role="menu">
          {items.map((m) => (
            <li key={m.label}>
              <button type="button" role="menuitem" onClick={() => { setOpen(false); m.onSelect() }}>
                {m.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
