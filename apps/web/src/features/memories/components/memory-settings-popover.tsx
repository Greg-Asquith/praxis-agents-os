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
import type { Workspace, WorkspaceUpdateRequest } from "@/features/workspaces/types"
import { getErrorMessage } from "@/lib/api/errors"

export function MemorySettingsPopover({ workspace }: { workspace: Workspace }) {
  const mutation = useUpdateWorkspaceMutation()

  function update(payload: MemorySwitchPayload) {
    mutation.mutate({ workspaceId: workspace.id, payload })
  }

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
        <MemorySwitch
          checked={workspace.memory_learning_enabled}
          description="Agents look back over finished conversations and remember what will help next time. Anything from a private conversation stays private to you."
          disabled={mutation.isPending}
          label="Learn From Past Conversations"
          onCheckedChange={(checked) => {
            update({ memory_learning_enabled: checked })
          }}
        />
        <MemorySwitch
          checked={workspace.memory_recall_enabled}
          description="Each conversation starts with the memories that relate to it. When off, agents still find memories by searching."
          disabled={mutation.isPending}
          label="Use Memories Automatically"
          onCheckedChange={(checked) => {
            update({ memory_recall_enabled: checked })
          }}
        />
        {mutation.error ? (
          <Alert variant="destructive">
            <AlertDescription>{getErrorMessage(mutation.error)}</AlertDescription>
          </Alert>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}

type MemorySwitchPayload = Pick<
  WorkspaceUpdateRequest,
  "memory_learning_enabled" | "memory_recall_enabled"
>

function MemorySwitch({
  checked,
  description,
  disabled,
  label,
  onCheckedChange,
}: {
  checked: boolean
  description: string
  disabled: boolean
  label: string
  onCheckedChange: (checked: boolean) => void
}) {
  const id = useId()

  return (
    <Field data-disabled={disabled} orientation="horizontal">
      <FieldContent>
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        <FieldDescription id={`${id}-description`}>{description}</FieldDescription>
      </FieldContent>
      <Switch
        aria-describedby={`${id}-description`}
        checked={checked}
        disabled={disabled}
        id={id}
        onCheckedChange={onCheckedChange}
      />
    </Field>
  )
}
