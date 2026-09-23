// apps/web/src/components/tool-ui/retained-result.tsx

import { useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"

import type { ResultPreview } from "@/components/tool-ui/result-preview"
import { retainedResultQueryOptions } from "@/components/tool-ui/result-preview-query"
import { Button } from "@/components/ui/button"

export function RetainedResult({
  children,
  preview,
  validate,
}: {
  children: (data: unknown, incomplete: boolean, control: ReactNode) => ReactNode
  preview: ResultPreview
  validate: (data: unknown) => boolean
}) {
  const [opened, setOpened] = useState(false)
  const result = useQuery({
    ...retainedResultQueryOptions(preview),
    enabled: opened,
    select: (data) => {
      if (!validate(data)) throw new Error("The saved result cannot be displayed as a report.")
      return data
    },
  })
  const complete = opened && result.isSuccess
  const control = (
    <div className="flex flex-wrap items-center gap-2">
      {complete ? (
        <p className="text-muted-foreground text-xs" role="status">
          Complete returned result loaded.
        </p>
      ) : (
        <Button
          variant="outline"
          size="sm"
          disabled={result.isFetching}
          onClick={() => {
            if (opened) void result.refetch()
            else setOpened(true)
          }}
        >
          {result.isFetching
            ? "Loading complete result…"
            : result.isError
              ? "Retry complete result"
              : "Open complete result"}
        </Button>
      )}
      {result.isError ? (
        <p className="text-destructive text-xs" role="alert">
          The complete result could not be loaded. The preview is still available.
        </p>
      ) : null}
    </div>
  )
  return children(complete ? result.data : preview.data, !complete, control)
}
