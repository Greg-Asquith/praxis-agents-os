// apps/web/src/features/memories/components/memory-settings-popover.tsx

import { useId } from "react"
import { Settings2Icon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field"
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Switch } from "@/components/ui/switch"
import { useUpdateWorkspaceMutation } from "@/features/workspaces/api/update-workspace"
import type { Workspace } from "@/features/workspaces/types"
import { getErrorMessage } from "@/lib/api/errors"

export function MemorySettingsPopover({ workspace }: { workspace: Workspace }) {
  const recallId = useId()
  const mutation = useUpdateWorkspaceMutation()

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button type="button" variant="outline">
            <Settings2Icon data-icon="inline-start" />
            Settings
          </Button>
        }
      />
      <PopoverContent align="end" className="w-[min(22rem,calc(100vw-2rem))] gap-3 p-4">
        <PopoverHeader>
          <PopoverTitle>Memory Settings</PopoverTitle>
        </PopoverHeader>
        <Field data-disabled={mutation.isPending} orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor={recallId}>Use Memories Automatically</FieldLabel>
            <FieldDescription id={`${recallId}-description`}>
              Each conversation starts with the memories that relate to it. When off, agents still
              find memories by searching.
            </FieldDescription>
          </FieldContent>
          <Switch
            aria-describedby={`${recallId}-description`}
            checked={workspace.memory_recall_enabled}
            disabled={mutation.isPending}
            id={recallId}
            onCheckedChange={(checked) => {
              mutation.mutate({
                workspaceId: workspace.id,
                payload: { memory_recall_enabled: checked },
              })
            }}
          />
        </Field>
        {mutation.error ? (
          <Alert variant="destructive">
            <AlertDescription>{getErrorMessage(mutation.error)}</AlertDescription>
          </Alert>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
