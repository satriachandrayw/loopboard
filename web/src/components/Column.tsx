import type { DragEvent } from 'react'
import type { ColumnData } from '../types'
import { COLUMN_RULES, REVIEW_LIMIT } from '../format'
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
      <h2 className="colh">
        <span>{data.label}</span>
        {data.column === 'review' ? (
          <span className={`limit${data.warn ? ' warn' : ''}`} title={data.warn ? 'Review is backing up' : undefined}>
            {`${data.count} / ${REVIEW_LIMIT} limit`}
          </span>
        ) : (
          <span className="count">{data.count}</span>
        )}
      </h2>
      {COLUMN_RULES[data.column] && <p className="rule">{COLUMN_RULES[data.column]}</p>}
      {data.cards.map((c) => (
        <Card key={c.key} card={c} nowSeconds={nowSeconds} onMove={(col) => onMove(c.key, col)} />
      ))}
    </section>
  )
}
