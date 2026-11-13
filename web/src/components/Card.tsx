import type { MouseEvent } from 'react'
import { ageSince, epicHref, FLAG_TEXT, RED_FLAGS, waitKind, who } from '../format'
import type { Card as CardT } from '../types'
import Menu from './Menu'

const MOVES: Record<string, { label: string; column: string }[]> = {
  backlog: [{ label: 'Todo', column: 'todo' }, { label: 'Canceled', column: 'canceled' }],
  todo: [{ label: 'Backlog', column: 'backlog' }, { label: 'Canceled', column: 'canceled' }],
}

interface Props {
  card: CardT
  nowSeconds: number
  onMove: (column: string) => void
}

function Waiting({ card, nowSeconds }: { card: CardT; nowSeconds: number }) {
  const age = ageSince(card.waiting_since, nowSeconds)
  if (card.column === 'backlog') return age ? <span className="wait-parked">{`parked ${age}`}</span> : null
  if (card.column === 'done') return age ? <span className="wait-done">{`done ${age}`}</span> : null
  const kind = waitKind(card.waiting_on)
  if (!kind) return null
  return (
    <span className={`wait-${kind}`}>
      {`${who(card.waiting_on)}${age ? ' · ' : ''}`}
      {age && (card.stalled ? <span className="stl">{age}</span> : age)}
    </span>
  )
}

export default function Card({ card, nowSeconds, onMove }: Props) {
  const moves = MOVES[card.column] ?? []
  const { done, total } = card.progress
  const open = (e: MouseEvent) => {
    // The title link, the Move menu and its items handle their own clicks.
    if ((e.target as HTMLElement).closest('a, button, [role="menu"]')) return
    window.location.hash = epicHref(card.key)
  }
  const pills = [
    ...card.flags.map((f) => ({ id: f, text: FLAG_TEXT[f] ?? f.replaceAll('_', ' '), red: RED_FLAGS.has(f) })),
    ...(card.review_owner ? [{ id: 'review_owner', text: `review · ${card.review_owner === 'human' ? 'you' : 'agent'}`, red: false }] : []),
  ]
  return (
    <article
      className={`card${card.stalled ? ' stalled' : ''}${card.column === 'done' ? ' done' : ''}`}
      draggable={card.column === 'backlog'}
      onClick={open}
      onDragStart={(e) => {
        e.dataTransfer?.setData('text/plain', card.key)
        e.dataTransfer?.setData('application/x-loopboard-column', card.column)
      }}
    >
      <div className="top">
        <span className="key">{card.key}</span>
        {card.stage && card.column !== 'done' && <span className="lbl">{card.stage}</span>}
        <span className="proj">{card.project_key}</span>
      </div>
      <h3 className="ti"><a href={epicHref(card.key)}>{card.title}</a></h3>
      {card.goal?.trim() && <p className="desc">{card.goal}</p>}
      {total > 0 && (
        <div className="pb" aria-hidden="true"><i style={{ width: `${Math.round((100 * done) / total)}%` }} /></div>
      )}
      <div className="w">
        <span>{card.column === 'backlog' && total === 0 ? '—' : `${done}/${total}`}</span>
        <Waiting card={card} nowSeconds={nowSeconds} />
      </div>
      {(pills.length > 0 || moves.length > 0) && (
        <div className="foot">
          {pills.map((p) => (
            <span key={p.id} className={`flag flag-${p.id}${p.red ? ' flag-red' : ''}`}>{p.text}</span>
          ))}
          {moves.length > 0 && (
            <Menu label="Move" className="move" items={moves.map((m) => ({ label: m.label, onSelect: () => onMove(m.column) }))} />
          )}
        </div>
      )}
    </article>
  )
}
