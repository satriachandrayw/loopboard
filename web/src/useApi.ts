import { useCallback, useEffect, useState } from 'react'
import { apiGet, AuthError } from './api'

// Loads a GET path; flags auth failures so the screen can show the token prompt.
export function useApi<T>(path: string, failure: string) {
  const [data, setData] = useState<T | null>(null)
  const [needsAuth, setNeedsAuth] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      setData(await apiGet<T>(path))
      setNeedsAuth(false)
      setError(null)
    } catch (e) {
      if (e instanceof AuthError) setNeedsAuth(true)
      else setError(failure)
    }
  }, [path, failure])
  useEffect(() => {
    void load()
  }, [load])
  return { data, setData, needsAuth, setNeedsAuth, error, setError, load }
}
