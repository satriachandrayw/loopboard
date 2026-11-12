import { useState } from 'react'
import type { Card as CardT } from '../types'

export const FLAG_TEXT: Record<string, string> = {
  awaiting_approval: 'awaiting your approval',
  awaiting_confirmation: 'awaiting your confirmation',
  blocked_needs_input: 'blocked: needs your input',
  blocked: 'blocked',
  merged_not_live: 'merged, not live',
}

const MOVES: Record<string, { label: string; column: string }[]> = {
  backlog: [{ label: 'Todo', column: 'todo' }, { label: 'Canceled', column: 'canceled' }],
  todo: [{ label: 'Backlog', column: 'backlog' }, { label: 'Canceled', column: 'canceled' }],
}

function waitClass(w: string | null): string {
  if (w?.startsWith('human:')) return 'wait-human'
  if (w?.startsWith('agent:')) return 'wait-agent'
  if (w?.startsWith('source:')) return 'wait-source'
  return ''
}

interface Props {
  card: CardT
  nowSeconds: number
  onMove: (column: string) => void
}

export default function Card({ card, nowSeconds, onMove }: Props) {
  const [open, setOpen] = useState(false)
  const moves = MOVES[card.column] ?? []
  const hours =
    card.waiting_since == null ? null : Math.max(0, Math.floor((nowSeconds - card.waiting_since) / 3600))
  return (
    <article
      className={`card${card.stalled ? ' stalled' : ''}`}
      draggable={card.column === 'backlog'}
      onDragStart={(e) => {
        e.dataTransfer?.setData('text/plain', card.key)
        e.dataTransfer?.setData('application/x-loopboard-column', card.column)
      }}
    >
      <h3>{card.title}</h3>
      <div className="meta">
        <span className="project-tag">{card.project_key}</span>
        {card.stage && <span className="stage">{card.stage}</span>}
        <span className="progress">{`${card.progress.done}/${card.progress.total}`}</span>
      </div>
      {card.review_owner && (
        <div className="review-owner">{`review · ${card.review_owner === 'human' ? 'you' : 'agent'}`}</div>
      )}
      {card.flags.map((f) => (
        <div key={f} className={`flag flag-${f}`}>{FLAG_TEXT[f] ?? f}</div>
      ))}
      {card.waiting_on && (
        <div className={`waiting ${waitClass(card.waiting_on)}`}>
          <span>{card.waiting_on}</span>
          {hours != null && <span>{`waiting ${hours}h`}</span>}
        </div>
      )}
      {moves.length > 0 && (
        <div className="move">
          <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
            Move
          </button>
          {open && (
            <ul role="menu">
              {moves.map((m) => (
                <li key={m.column}>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setOpen(false)
                      onMove(m.column)
                    }}
                  >
                    {m.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  )
}
