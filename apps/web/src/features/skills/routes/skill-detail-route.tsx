// apps/web/src/features/skills/routes/skill-detail-route.tsx

import { useState } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"
import { useNavigate, useParams } from "@tanstack/react-router"
import { Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { FormSection } from "@/components/forms/form-section"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useDeleteSkillMutation } from "@/features/skills/api/delete-skill"
import { useSkillQuery } from "@/features/skills/api/get-skill"
import { useUpdateSkillMutation } from "@/features/skills/api/update-skill"
import { SkillDocumentsSection } from "@/features/skills/components/skill-documents-section"
import { SkillForm } from "@/features/skills/components/skill-form"
import { skillDisplayName } from "@/features/skills/format"
import type { SkillUpdateRequest } from "@/features/skills/types"
import { getErrorMessage } from "@/lib/api/errors"

export function SkillDetailRoute() {
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const skillId = requireSkillId(params.skillId)
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { data: skill } = useSkillQuery(skillId)
  const canManage = skill.scope === "workspace" || user.is_super_admin
  const updateSkillMutation = useUpdateSkillMutation()
  const deleteSkillMutation = useDeleteSkillMutation()
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  async function handleUpdateSkill(payload: SkillUpdateRequest) {
    setDeleteError(null)
    await updateSkillMutation.mutateAsync({ payload, skillId: skill.id })
    await navigate({ to: "/skills" })
  }

  async function handleDeleteSkill() {
    setDeleteError(null)

    try {
      await deleteSkillMutation.mutateAsync({ id: skill.id, scope: skill.scope })
      await navigate({ to: "/skills" })
    } catch (mutationError) {
      setDeleteError(getErrorMessage(mutationError))
      setDeleteDialogOpen(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-heading text-2xl font-semibold tracking-normal">
                {skillDisplayName(skill)}
              </h1>
              {!skill.is_active ? <Badge variant="outline">Inactive</Badge> : null}
              {skill.scope === "platform" ? <Badge variant="secondary">Platform</Badge> : null}
              {skill.scope === "workspace" && skill.is_favorite ? (
                <Badge variant="outline">Favorite</Badge>
              ) : null}
            </div>
            <p className="text-muted-foreground max-w-3xl text-sm">{skill.description}</p>
          </div>
        </div>
        {canManage ? (
          <>
            <Button
              disabled={deleteSkillMutation.isPending}
              onClick={() => {
                setDeleteDialogOpen(true)
              }}
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              {deleteSkillMutation.isPending ? "Deleting" : "Delete Skill"}
            </Button>
            <ConfirmDialog
              confirmIcon={<Trash2Icon data-icon="inline-start" />}
              confirmLabel="Delete Skill"
              confirmPendingLabel="Deleting"
              description={
                skill.scope === "platform"
                  ? `This removes ${skill.name} from every workspace.`
                  : `This removes ${skill.name} and its uploaded reference documents from the workspace.`
              }
              isPending={deleteSkillMutation.isPending}
              onConfirm={handleDeleteSkill}
              onOpenChange={setDeleteDialogOpen}
              open={deleteDialogOpen}
              title="Delete skill?"
            />
          </>
        ) : null}
      </div>

      {deleteError ? (
        <Alert variant="destructive">
          <AlertTitle>Skill not deleted</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      ) : null}
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        {canManage ? (
          <SkillForm
            key={`${skill.id}:${skill.updated_at}`}
            cancelLabel="Back to Skills"
            isSubmitting={updateSkillMutation.isPending}
            mode="edit"
            onSubmit={handleUpdateSkill}
            skill={skill}
          >
            {skill.scope === "workspace" ? <SkillDocumentsSection skillId={skill.id} /> : null}
          </SkillForm>
        ) : (
          <>
            <Alert>
              <AlertTitle>Managed by Admins</AlertTitle>
              <AlertDescription>
                This skill is available in every workspace. Only a platform admin can change it.
              </AlertDescription>
            </Alert>
            <FormSection
              description="These instructions are loaded when an agent activates the skill."
              eyebrow="Guidance"
              title="Instructions"
            >
              <p className="text-sm leading-6 whitespace-pre-wrap">{skill.instructions}</p>
            </FormSection>
          </>
        )}
      </div>
    </div>
  )
}

function requireSkillId(value: string | undefined) {
  if (!value) {
    throw new Error("Skill route is missing a skill id.")
  }

  return value
}
