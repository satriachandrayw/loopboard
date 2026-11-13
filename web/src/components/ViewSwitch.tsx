// Epics | Tasks: the epic board (home) and the per-project Tasks board.
export default function ViewSwitch({ view }: { view: 'epics' | 'tasks' }) {
  const link = (v: 'epics' | 'tasks', href: string, label: string) => (
    <a href={href} className={view === v ? 'on' : undefined} aria-current={view === v ? 'page' : undefined}>{label}</a>
  )
  return (
    <div className="seg" role="group" aria-label="View">
      {link('epics', '#/board', 'Epics')}
      {link('tasks', '#/tasks', 'Tasks')}
    </div>
  )
}
