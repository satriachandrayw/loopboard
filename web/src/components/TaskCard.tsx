import type { MouseEvent } from 'react'
import { ageSince, FLAG_TEXT, linksText, RED_FLAGS, taskHref, waitKind, who } from '../format'
import type { TaskView } from '../types'

interface Props {
  task: TaskView
  nowSeconds: number
  draggable: boolean
}

function linksLine(task: TaskView): string {
  const links = linksText(task.links_summary)
  const base = links || (task.status === 'todo' ? 'no links yet' : 'no links · moved by hand')
  return task.refs.length ? `${base} · ref ${task.refs.join(', ')}` : base
}

function Waiting({ task, nowSeconds }: { task: TaskView; nowSeconds: number }) {
  if (task.status === 'done') {
    const age = ageSince(task.last_activity_at, nowSeconds)
    return age ? <span className="wait-done">{`done ${age}`}</span> : null
  }
  const age = ageSince(task.waiting_since, nowSeconds)
  const kind = waitKind(task.waiting_on)
  if (!kind) return null
  return (
    <span className={`wait-${kind}`}>
      {`${who(task.waiting_on)}${age ? ' · ' : ''}`}
      {age && (task.stalled ? <span className="stl">{age}</span> : age)}
    </span>
  )
}

// One task on the Tasks board. Only a task without links is dragged between columns.
export default function TaskCard({ task, nowSeconds, draggable }: Props) {
  const open = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest('a, button')) return
    window.location.hash = taskHref(task.key)
  }
  return (
    <article
      className={`card task-card${task.stalled ? ' stalled' : ''}${task.status === 'done' ? ' done' : ''}`}
      draggable={draggable}
      onClick={open}
      onDragStart={(e) => {
        if (!draggable) return
        e.dataTransfer?.setData('text/plain', task.key)
        e.dataTransfer?.setData('application/x-loopboard-task', task.status)
      }}
    >
      <div className="top">
        <span className="key">{task.key}</span>
        <span className={`typ${task.type === 'bug' ? ' bug' : ''}`}>{task.type}</span>
      </div>
      <h3 className="ti"><a href={taskHref(task.key)}>{task.summary}</a></h3>
      <p className="links">{linksLine(task)}</p>
      <div className="w">
        <span />
        <Waiting task={task} nowSeconds={nowSeconds} />
      </div>
      {task.flags.length > 0 && (
        <div className="foot">
          {task.flags.map((f) => (
            <span key={f} className={`flag flag-${f}${RED_FLAGS.has(f) ? ' flag-red' : ''}`}>
              {FLAG_TEXT[f] ?? f.replaceAll('_', ' ')}
            </span>
          ))}
        </div>
      )}
    </article>
  )
}
