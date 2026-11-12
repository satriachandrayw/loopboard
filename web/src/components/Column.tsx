import type { DragEvent } from 'react'
import type { ColumnData } from '../types'
import Card from './Card'

interface Props {
  data: ColumnData
  nowSeconds: number
  onMove: (key: string, column: string) => void
  onDropCard?: (e: DragEvent<HTMLElement>) => void
}

export default function Column({ data, nowSeconds, onMove, onDropCard }: Props) {
  return (
    <section
      className={`column${data.warn ? ' warn' : ''}`}
      data-column={data.column}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDropCard}
    >
      <h2>
        {data.label} <span className="count">{data.count}</span>
      </h2>
      {data.warn && <div className="warn-text">Review is backing up</div>}
      {data.cards.map((c) => (
        <Card key={c.key} card={c} nowSeconds={nowSeconds} onMove={(col) => onMove(c.key, col)} />
      ))}
    </section>
  )
}
