import { useCallback, useEffect, useState } from 'react'

/**
 * Custom hook: run an async loader, track loading/error/data, and expose
 * reload() so a page can refresh after a change (e.g. after RSVPing).
 * Every page needs this pattern; writing it once keeps pages short.
 */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const run = useCallback(loader, deps)

  const reload = useCallback(async () => {
    try {
      setError(null)
      setData(await run())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }, [run])

  useEffect(() => {
    setLoading(true)
    reload()
  }, [reload])

  return { data, error, loading, reload }
}
