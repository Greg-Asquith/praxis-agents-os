// apps/web/src/features/integrations/components/context-group-dialog.tsx

import { useMemo, useState } from "react"
import { SearchIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useCreateContextGroupMutation } from "@/features/integrations/api/create-context-group"
import { useUpdateContextGroupMutation } from "@/features/integrations/api/update-context-group"
import { ProviderMark } from "@/features/integrations/components/provider-mark"
import type {
  IntegrationContextGroup,
  IntegrationProvider,
  IntegrationResource,
} from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"
import { titleCaseToken } from "@/lib/format"

type ResourceSection = {
  providerKey: string
  resources: IntegrationResource[]
}

export function ContextGroupDialog({
  group,
  onOpenChange,
  open,
  providers,
  resources,
}: {
  group: IntegrationContextGroup | null
  onOpenChange: (open: boolean) => void
  open: boolean
  providers: IntegrationProvider[]
  resources: IntegrationResource[]
}) {
  const createMutation = useCreateContextGroupMutation()
  const updateMutation = useUpdateContextGroupMutation()
  const [name, setName] = useState(group?.name ?? "")
  const [search, setSearch] = useState("")
  const [selectedIds, setSelectedIds] = useState(
    () => new Set(group?.members.map((item) => item.id))
  )
  const [error, setError] = useState<string | null>(null)
  const editableResources = useMemo(
    () =>
      resources.filter(
        (resource) =>
          resource.enabled &&
          resource.availability === "available" &&
          (resource.connection_status === "active" || resource.connection_status === "degraded")
      ),
    [resources]
  )
  const sections = useMemo(
    () => groupResourcesByProvider(editableResources, search),
    [editableResources, search]
  )
  const providerNames = useMemo(
    () => new Map(providers.map((provider) => [provider.provider_key, provider.display_name])),
    [providers]
  )
  const isPending = createMutation.isPending || updateMutation.isPending

  function handleOpenChange(nextOpen: boolean) {
    if (!isPending) {
      onOpenChange(nextOpen)
    }
  }

  function toggleResource(resourceId: string, checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (checked) {
        next.add(resourceId)
      } else {
        next.delete(resourceId)
      }
      return next
    })
  }

  async function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedName = name.trim()
    if (!normalizedName) {
      setError("Enter a name for this context group.")
      return
    }
    setError(null)
    const payload = { name: normalizedName, resource_ids: [...selectedIds] }
    try {
      if (group) {
        await updateMutation.mutateAsync({ groupId: group.id, payload })
      } else {
        await createMutation.mutateAsync(payload)
      }
      onOpenChange(false)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <form
          className="flex min-h-0 flex-col gap-4"
          onSubmit={(event) => {
            void handleSubmit(event)
          }}
        >
          <DialogHeader>
            <DialogTitle>{group ? "Edit Context Group" : "New Context Group"}</DialogTitle>
            <DialogDescription>
              Pick what agents should use together for a client or project.
            </DialogDescription>
          </DialogHeader>

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Context group not saved</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <Field>
            <FieldLabel htmlFor="context-group-name">Name</FieldLabel>
            <Input
              disabled={isPending}
              id="context-group-name"
              maxLength={120}
              onChange={(event) => {
                setName(event.target.value)
              }}
              placeholder="Client or project name"
              value={name}
            />
            <FieldDescription>
              Use a name your team will recognize in chat and schedules.
            </FieldDescription>
            {!name.trim() && error ? <FieldError>Enter a group name.</FieldError> : null}
          </Field>

          <Field>
            <FieldLabel htmlFor="context-resource-search">Resources</FieldLabel>
            <div className="relative">
              <SearchIcon className="text-muted-foreground pointer-events-none absolute top-2 left-2.5 size-4" />
              <Input
                className="pl-8"
                disabled={isPending}
                id="context-resource-search"
                onChange={(event) => {
                  setSearch(event.target.value)
                }}
                placeholder="Search connected resources"
                value={search}
              />
            </div>
          </Field>

          <div className="border-border max-h-72 overflow-y-auto rounded-lg border p-2">
            {sections.length > 0 ? (
              <div className="flex flex-col gap-3">
                {sections.map((section) => (
                  <section className="flex flex-col gap-1" key={section.providerKey}>
                    <div className="text-muted-foreground flex items-center justify-between px-2 py-1 text-xs font-medium">
                      <span className="flex items-center gap-1.5">
                        <ProviderMark className="size-3.5" providerKey={section.providerKey} />
                        {providerNames.get(section.providerKey) ??
                          titleCaseToken(section.providerKey, "Provider")}
                      </span>
                      <span>{section.resources.length}</span>
                    </div>
                    {section.resources.map((resource) => (
                      <label
                        className="hover:bg-muted/50 flex min-w-0 cursor-pointer items-start gap-3 rounded-md px-2 py-2"
                        htmlFor={`context-resource-${resource.id}`}
                        key={resource.id}
                      >
                        <Checkbox
                          checked={selectedIds.has(resource.id)}
                          className="mt-0.5"
                          disabled={isPending}
                          id={`context-resource-${resource.id}`}
                          onCheckedChange={(checked) => {
                            toggleResource(resource.id, checked)
                          }}
                        />
                        <span className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate text-sm font-medium">
                            {resource.display_name}
                          </span>
                          <span className="text-muted-foreground truncate text-xs">
                            {resource.connection_label ?? resource.external_id}
                          </span>
                        </span>
                      </label>
                    ))}
                  </section>
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground px-2 py-8 text-center text-sm">
                {editableResources.length === 0
                  ? "Nothing to pick from yet. Connect an account on the Integrations page and choose what agents can use."
                  : "No resources match your search."}
              </p>
            )}
          </div>
          {selectedIds.size > 0 ? (
            <p className="text-muted-foreground text-xs">
              {selectedIds.size === 1
                ? "1 resource selected"
                : `${String(selectedIds.size)} resources selected`}
            </p>
          ) : null}

          <DialogFooter>
            <DialogClose render={<Button disabled={isPending} variant="outline" />}>
              Cancel
            </DialogClose>
            <Button disabled={isPending} type="submit">
              {isPending ? "Saving…" : group ? "Save Changes" : "Create Group"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function groupResourcesByProvider(resources: IntegrationResource[], search: string) {
  const needle = search.trim().toLocaleLowerCase()
  const grouped = new Map<string, IntegrationResource[]>()
  for (const resource of resources) {
    const providerKey = resource.provider_key ?? "other"
    const searchable = [
      resource.display_name,
      resource.external_id,
      resource.connection_label ?? "",
      providerKey,
    ]
      .join(" ")
      .toLocaleLowerCase()
    if (needle && !searchable.includes(needle)) {
      continue
    }
    const providerResources = grouped.get(providerKey) ?? []
    providerResources.push(resource)
    grouped.set(providerKey, providerResources)
  }
  return [...grouped]
    .toSorted(([left], [right]) => left.localeCompare(right))
    .map(([providerKey, providerResources]): ResourceSection => ({
      providerKey,
      resources: providerResources.toSorted((left, right) =>
        left.display_name.localeCompare(right.display_name, undefined, { sensitivity: "base" })
      ),
    }))
}
