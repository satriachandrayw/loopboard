import type { EpicEvent } from '../types'

// Events arrive newest first from the server; rendered in that order.
export default function ActivityLog({ events }: { events: EpicEvent[] }) {
  return (
    <section className="activity">
      <h2>Activity</h2>
      <ol>
        {events.map((e) => (
          <li key={e.id}>
            <time dateTime={new Date(e.at * 1000).toISOString()}>{new Date(e.at * 1000).toISOString().slice(0, 16).replace('T', ' ')}</time>
            <span>{` ${e.kind} · ${e.actor}`}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
