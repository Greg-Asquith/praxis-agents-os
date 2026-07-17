// apps/web/src/features/conversations/hooks/use-elapsed-seconds.ts

import { useEffect, useState } from "react"

export function useElapsedSeconds(running: boolean) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  useEffect(() => {
    if (!running) {
      return
    }

    const startedAt = Date.now()
    const intervalId = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [running])

  return elapsedSeconds
}
