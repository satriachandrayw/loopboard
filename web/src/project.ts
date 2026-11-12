import { useEffect, useSyncExternalStore } from 'react'
import { useApi } from './useApi'
import type { Project } from './types'

// The project chip choice, shared by every screen and kept across reloads. '' = all projects.
const KEY = 'loopboard.project'
const listeners = new Set<() => void>()

export const getProject = (): string => localStorage.getItem(KEY) ?? ''

export function setProject(key: string): void {
  if (key) localStorage.setItem(KEY, key)
  else localStorage.removeItem(KEY)
  listeners.forEach((l) => l())
}

const subscribe = (cb: () => void) => {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

export function useProject(): [string, (key: string) => void] {
  return [useSyncExternalStore(subscribe, getProject), setProject]
}

export const withProject = (path: string, project: string) =>
  project ? `${path}?project=${encodeURIComponent(project)}` : path

// Loads /api/projects; a stored choice that no longer exists falls back to all projects.
export function useProjects(): Project[] | null {
  const { data } = useApi<Project[]>('/api/projects', 'Could not load projects.')
  const [project] = useProject()
  const list = Array.isArray(data) ? data : null
  useEffect(() => {
    if (list && project && !list.some((p) => p.key === project)) setProject('')
  }, [list, project])
  return list
}
