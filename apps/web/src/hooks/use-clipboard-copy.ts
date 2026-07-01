// apps/web/src/hooks/use-clipboard-copy.ts

import { useCallback, useEffect, useRef, useState } from "react"

export function useClipboardCopy({ resetAfterMs = 2000 } = {}) {
  const [copied, setCopied] = useState(false)
  const resetTimeoutRef = useRef<number | null>(null)

  const copy = useCallback(
    async (value: string) => {
      try {
        await navigator.clipboard.writeText(value)
      } catch {
        return false
      }

      setCopied(true)
      if (resetTimeoutRef.current !== null) {
        window.clearTimeout(resetTimeoutRef.current)
      }
      resetTimeoutRef.current = window.setTimeout(() => {
        setCopied(false)
        resetTimeoutRef.current = null
      }, resetAfterMs)
      return true
    },
    [resetAfterMs]
  )

  useEffect(() => {
    return () => {
      if (resetTimeoutRef.current !== null) {
        window.clearTimeout(resetTimeoutRef.current)
      }
    }
  }, [])

  return { copied, copy }
}
