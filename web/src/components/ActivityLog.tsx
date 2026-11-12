import { formatAge, nowSeconds } from '../format'
import type { EpicEvent } from '../types'

// Events arrive newest first from the server; rendered in that order.
export default function ActivityLog({ events }: { events: EpicEvent[] }) {
  const now = nowSeconds()
  return (
    <section className="activity">
      <h2 className="sec">Activity</h2>
      <ol>
        {events.map((e) => (
          <li key={e.id} className="log">
            <b>{e.actor}</b>
            <span>{` ${e.kind.replaceAll('_', ' ')} · `}</span>
            <time dateTime={new Date(e.at * 1000).toISOString()} title={new Date(e.at * 1000).toISOString().slice(0, 16).replace('T', ' ')}>
              {formatAge(now - e.at)}
            </time>
          </li>
        ))}
      </ol>
    </section>
  )
}
