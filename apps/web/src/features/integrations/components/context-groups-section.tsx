// apps/web/src/features/integrations/components/context-groups-section.tsx

import { useState } from "react"
import { Layers3Icon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useDeleteContextGroupMutation } from "@/features/integrations/api/delete-context-group"
import { useContextGroupsQuery } from "@/features/integrations/api/list-context-groups"
import { useIntegrationResourcesQuery } from "@/features/integrations/api/list-integration-resources"
import { ContextGroupDialog } from "@/features/integrations/components/context-group-dialog"
import type { IntegrationContextGroup } from "@/features/integrations/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { titleCaseToken } from "@/lib/format"
import { getErrorMessage } from "@/lib/api/errors"

export function ContextGroupsSection() {
  const { workspace } = useActiveWorkspace()
  const { data } = useContextGroupsQuery()
  const { data: resources } = useIntegrationResourcesQuery()
  const deleteMutation = useDeleteContextGroupMutation()
  const [editingGroup, setEditingGroup] = useState<IntegrationContextGroup | null>(null)
  const [groupDialogOpen, setGroupDialogOpen] = useState(false)
  const [deletingGroup, setDeletingGroup] = useState<IntegrationContextGroup | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const canEdit =
    workspace.current_user_role !== null && workspace.current_user_role !== "read_only"
  const providerByResourceId = new Map(
    resources.map((resource) => [resource.id, resource.provider_key])
  )

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

  return (
    <Card>
      <CardHeader>
        <CardTitle>Context Groups</CardTitle>
        <CardDescription>
          Bundle resources that agents should use together in conversations and schedules.
        </CardDescription>
        {canEdit ? (
          <CardAction>
            <Button
              onClick={() => {
                openGroupDialog(null)
              }}
              size="sm"
            >
              <PlusIcon data-icon="inline-start" />
              New Group
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {deleteError ? (
          <Alert variant="destructive">
            <AlertTitle>Context group not deleted</AlertTitle>
            <AlertDescription>{deleteError}</AlertDescription>
          </Alert>
        ) : null}
        {data.items.length > 0 ? (
          <div className="divide-border divide-y rounded-lg border">
            {data.items.map((group) => {
              const providers = [
                ...new Set(
                  group.members.map((member) => providerByResourceId.get(member.id) ?? "other")
                ),
              ].toSorted()
              return (
                <div
                  className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between"
                  key={group.id}
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="bg-muted mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
                      <Layers3Icon className="text-muted-foreground size-4" />
                    </span>
                    <div className="flex min-w-0 flex-col gap-1.5">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="truncate font-medium">{group.name}</span>
                        <span className="text-muted-foreground text-xs">
                          {group.members.length}{" "}
                          {group.members.length === 1 ? "resource" : "resources"}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {providers.map((providerKey) => (
                          <Badge key={providerKey} variant="secondary">
                            {titleCaseToken(providerKey, "Provider")}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                  {canEdit ? (
                    <div className="flex shrink-0 items-center gap-1 self-end sm:self-auto">
                      <Button
                        aria-label={`Edit ${group.name}`}
                        onClick={() => {
                          openGroupDialog(group)
                        }}
                        size="icon-sm"
                        variant="ghost"
                      >
                        <PencilIcon />
                      </Button>
                      <Button
                        aria-label={`Delete ${group.name}`}
                        onClick={() => {
                          setDeletingGroup(group)
                        }}
                        size="icon-sm"
                        variant="ghost"
                      >
                        <Trash2Icon />
                      </Button>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="border-border flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center">
            <Layers3Icon className="text-muted-foreground size-5" />
            <p className="font-medium">No context groups yet</p>
            <p className="text-muted-foreground max-w-md text-sm">
              {canEdit
                ? "Create a group to switch a conversation or schedule between client resources in one step."
                : "Workspace editors can create groups from connected resources."}
            </p>
          </div>
        )}
      </CardContent>

      {groupDialogOpen ? (
        <ContextGroupDialog
          group={editingGroup}
          key={editingGroup?.id ?? "new"}
          onOpenChange={setGroupDialogOpen}
          open={groupDialogOpen}
          resources={resources}
        />
      ) : null}
      <ConfirmDialog
        confirmLabel="Delete Group"
        confirmPendingLabel="Deleting…"
        description={
          deletingGroup
            ? `Runs using “${deletingGroup.name}” will fall back to no context.`
            : "Runs using this group will fall back to no context."
        }
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
        onOpenChange={(open) => {
          if (!open) {
            setDeletingGroup(null)
          }
        }}
        open={deletingGroup !== null}
        title="Delete Context Group?"
      />
    </Card>
  )
}
