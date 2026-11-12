import type { Task } from '../types'

// One task row in epic detail: a coloured dot for its group, the title and its source chip.
export default function TaskCard({ task }: { task: Task }) {
  const source = task.source ?? task.ref.split(':')[0]
  return (
    <article className={`task dot-${task.category}`}>
      <i className="dot" aria-hidden="true" />
      <span className="task-title">
        {task.url ? <a href={task.url} target="_blank" rel="noreferrer">{task.title}</a> : task.title}
      </span>
      {task.waiting_on && <span className="task-wait">{task.waiting_on}</span>}
      <span className="src">{source}</span>
    </article>
  )
}
