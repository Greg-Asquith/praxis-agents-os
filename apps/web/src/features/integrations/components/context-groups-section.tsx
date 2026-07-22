// apps/web/src/features/integrations/components/context-groups-section.tsx

import { useEffect, useState } from "react"
import { EllipsisIcon, Layers3Icon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { EmptyState } from "@/components/ui/empty-state"
import { useDeleteContextGroupMutation } from "@/features/integrations/api/delete-context-group"
import { useContextGroupsQuery } from "@/features/integrations/api/list-context-groups"
import { useIntegrationProvidersQuery } from "@/features/integrations/api/list-providers"
import { useIntegrationResourcesQuery } from "@/features/integrations/api/list-integration-resources"
import { ContextGroupDialog } from "@/features/integrations/components/context-group-dialog"
import { ProviderMark } from "@/features/integrations/components/provider-mark"
import type { IntegrationContextGroup } from "@/features/integrations/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { loadIntegrationUiModules } from "@/integrations/registry"
import { titleCaseToken } from "@/lib/format"
import { getErrorMessage } from "@/lib/api/errors"

export function ContextGroupsSection() {
  const { workspace } = useActiveWorkspace()
  const { data } = useContextGroupsQuery()
  const { data: providers } = useIntegrationProvidersQuery()
  const { data: resources } = useIntegrationResourcesQuery()
  const deleteMutation = useDeleteContextGroupMutation()
  const [editingGroup, setEditingGroup] = useState<IntegrationContextGroup | null>(null)
  const [groupDialogOpen, setGroupDialogOpen] = useState(false)
  const [deletingGroup, setDeletingGroup] = useState<IntegrationContextGroup | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const canEdit =
    workspace.current_user_role !== null && workspace.current_user_role !== "read_only"
  const providerKeySignature = providers.map((provider) => provider.provider_key).join("|")
  const providerByResourceId = new Map(
    resources.map((resource) => [resource.id, resource.provider_key])
  )
  const providerNames = new Map(
    providers.map((provider) => [provider.provider_key, provider.display_name])
  )

  useEffect(() => {
    void loadIntegrationUiModules(providerKeySignature ? providerKeySignature.split("|") : [])
  }, [providerKeySignature])

  function openGroupDialog(group: IntegrationContextGroup | null) {
    setEditingGroup(group)
    setGroupDialogOpen(true)
  }

  async function handleDelete() {
    if (!deletingGroup) {
      return
    }
    setDeleteError(null)
    try {
      await deleteMutation.mutateAsync(deletingGroup.id)
      setDeletingGroup(null)
    } catch (error) {
      setDeleteError(getErrorMessage(error))
    }
  }

  const newGroupButton = canEdit ? (
    <Button
      onClick={() => {
        openGroupDialog(null)
      }}
    >
      <PlusIcon data-icon="inline-start" />
      New Group
    </Button>
  ) : undefined

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={newGroupButton}
        description="Save a set of accounts agents use together, then pick it when starting a conversation or schedule."
        title="Context Groups"
      />
      {deleteError ? (
        <Alert variant="destructive">
          <AlertTitle>Context group not deleted</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      ) : null}
      {data.items.length > 0 ? (
        <div className="divide-border divide-y" aria-label="Context groups">
          {data.items.map((group) => {
            const providerKeys = [
              ...new Set(
                group.members.map((member) => providerByResourceId.get(member.id) ?? "other")
              ),
            ].toSorted()
            return (
              <div
                className="flex min-h-20 items-center gap-3 px-2 py-4 sm:gap-4 sm:px-3"
                key={group.id}
              >
                <GroupMarks providerKeys={providerKeys} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{group.name}</p>
                  <p className="text-muted-foreground mt-0.5 truncate text-sm">
                    {groupSummary(group.members.length, providerKeys, providerNames)}
                  </p>
                </div>
                {canEdit ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          aria-label={`Actions for ${group.name}`}
                          size="icon-sm"
                          variant="ghost"
                        />
                      }
                    >
                      <EllipsisIcon />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onClick={() => {
                          openGroupDialog(group)
                        }}
                      >
                        <PencilIcon />
                        Edit Group
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => {
                          setDeletingGroup(group)
                        }}
                        variant="destructive"
                      >
                        <Trash2Icon />
                        Delete Group
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : (
        <EmptyState
          action={newGroupButton}
          description={
            canEdit
              ? "Group the accounts a client or project uses so you can pick them together in chat and schedules."
              : "Workspace editors can create groups from connected accounts."
          }
          icon={<Layers3Icon className="size-5" />}
          title="No context groups yet"
        />
      )}

      {groupDialogOpen ? (
        <ContextGroupDialog
          group={editingGroup}
          key={editingGroup?.id ?? "new"}
          onOpenChange={setGroupDialogOpen}
          open={groupDialogOpen}
          providers={providers}
          resources={resources}
        />
      ) : null}
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete Group"
        confirmPendingLabel="Deleting"
        description={
          deletingGroup
            ? `Conversations and schedules using “${deletingGroup.name}” will run without it.`
            : "Conversations and schedules using this group will run without it."
        }
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
        onOpenChange={(open) => {
          if (!open) {
            setDeletingGroup(null)
          }
        }}
        open={deletingGroup !== null}
        title="Delete this group?"
      />
    </div>
  )
}

function GroupMarks({ providerKeys }: { providerKeys: string[] }) {
  const shown = providerKeys.slice(0, 3)
  const extra = providerKeys.length - shown.length

  if (shown.length === 0) {
    return (
      <span className="border-border bg-background text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg border shadow-xs">
        <Layers3Icon className="size-4" aria-hidden="true" />
      </span>
    )
  }

  return (
    <span className="flex shrink-0 items-center gap-1">
      {shown.map((providerKey) => (
        <span
          className="border-border bg-background flex size-9 items-center justify-center rounded-lg border shadow-xs"
          key={providerKey}
        >
          <ProviderMark className="size-4" providerKey={providerKey} />
        </span>
      ))}
      {extra > 0 ? (
        <span className="border-border bg-background text-muted-foreground flex size-9 items-center justify-center rounded-lg border text-xs shadow-xs">
          +{extra}
        </span>
      ) : null}
    </span>
  )
}

function groupSummary(
  memberCount: number,
  providerKeys: string[],
  providerNames: Map<string, string>
) {
  if (memberCount === 0) {
    return "Nothing in this group yet"
  }
  const names = providerKeys.map(
    (providerKey) => providerNames.get(providerKey) ?? titleCaseToken(providerKey, "Provider")
  )
  const count = memberCount === 1 ? "1 resource" : `${String(memberCount)} resources`
  return `${count} from ${joinNames(names)}`
}

function joinNames(names: string[]) {
  if (names.length <= 1) {
    return names[0] ?? ""
  }
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1) ?? ""}`
}
