import { useProject } from '../project'
import type { Project } from '../types'

// Single-select project filter: "All projects" plus one chip per project.
export default function ProjectChips({ projects }: { projects: Project[] | null }) {
  const [project, setProject] = useProject()
  const chip = (key: string, label: string) => (
    <button key={key || '*'} type="button" className={`chip${project === key ? ' on' : ''}`}
      aria-pressed={project === key} onClick={() => setProject(key)}>
      {label}
    </button>
  )
  return (
    <div className="chips" role="group" aria-label="Project">
      {chip('', 'All projects')}
      {(projects ?? []).map((p) => chip(p.key, p.name))}
    </div>
  )
}
