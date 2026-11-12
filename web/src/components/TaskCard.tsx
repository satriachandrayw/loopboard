import type { Task } from '../types'

export default function TaskCard({ task }: { task: Task }) {
  return (
    <article className="card task">
      <h3>
        {task.url ? <a href={task.url} target="_blank" rel="noreferrer">{task.title}</a> : task.title}
      </h3>
      {task.waiting_on && <div className="waiting">{task.waiting_on}</div>}
    </article>
  )
}
