// apps/web/src/features/skills/routes/skill-detail-route.tsx

import { useState } from "react"
import { Link, useNavigate, useParams } from "@tanstack/react-router"
import { ArrowLeftIcon, ClockIcon, FileTextIcon, SparklesIcon, Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MetricCard } from "@/components/ui/metric-card"
import { useDeleteSkillMutation } from "@/features/skills/api/delete-skill"
import { useSkillQuery } from "@/features/skills/api/get-skill"
import { useUpdateSkillMutation } from "@/features/skills/api/update-skill"
import { SkillDocumentsSection } from "@/features/skills/components/skill-documents-section"
import { SkillForm } from "@/features/skills/components/skill-form"
import { skillDisplayName } from "@/features/skills/format"
import type { SkillUpdateRequest } from "@/features/skills/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, pluralize } from "@/lib/format"

export function SkillDetailRoute() {
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const skillId = requireSkillId(params.skillId)
  const { data: skill } = useSkillQuery(skillId)
  const updateSkillMutation = useUpdateSkillMutation()
  const deleteSkillMutation = useDeleteSkillMutation()
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [saved, setSaved] = useState(false)
  const documentCount = Object.keys(skill.documentation_refs).length

  async function handleUpdateSkill(payload: SkillUpdateRequest) {
    setDeleteError(null)
    setSaved(false)
    await updateSkillMutation.mutateAsync({ payload, skillId: skill.id })
    setSaved(true)
  }

  async function handleDeleteSkill() {
    setDeleteError(null)
    setSaved(false)

    try {
      await deleteSkillMutation.mutateAsync(skill.id)
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
          <Button className="w-fit" size="sm" variant="outline" render={<Link to="/skills" />}>
            <ArrowLeftIcon data-icon="inline-start" />
            Skills
          </Button>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={skill.is_active ? "default" : "secondary"}>
                {skill.is_active ? "Active" : "Inactive"}
              </Badge>
              {skill.is_favorite ? <Badge variant="outline">Favorite</Badge> : null}
            </div>
            <h1 className="font-heading text-2xl font-semibold tracking-normal">
              {skillDisplayName(skill)}
            </h1>
            <p className="text-muted-foreground max-w-3xl text-sm">{skill.description}</p>
          </div>
        </div>
        <Button
          disabled={deleteSkillMutation.isPending}
          onClick={() => {
            setDeleteDialogOpen(true)
          }}
          variant="destructive"
        >
          <Trash2Icon data-icon="inline-start" />
          {deleteSkillMutation.isPending ? "Deleting" : "Delete skill"}
        </Button>
        <ConfirmDialog
          confirmIcon={<Trash2Icon data-icon="inline-start" />}
          confirmLabel="Delete skill"
          confirmPendingLabel="Deleting"
          description={`This removes ${skill.name} and its uploaded reference documents from the workspace.`}
          isPending={deleteSkillMutation.isPending}
          onConfirm={handleDeleteSkill}
          onOpenChange={setDeleteDialogOpen}
          open={deleteDialogOpen}
          title="Delete skill?"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          description={skill.name}
          icon={<SparklesIcon className="size-4" />}
          title="Identifier"
        />
        <MetricCard
          description={`${String(documentCount)} ${pluralize(documentCount, "document")} uploaded`}
          icon={<FileTextIcon className="size-4" />}
          title="Documents"
        />
        <MetricCard
          description={formatDateTime(skill.last_used_at)}
          icon={<ClockIcon className="size-4" />}
          title="Last used"
        />
      </div>

      {deleteError ? (
        <Alert variant="destructive">
          <AlertTitle>Skill not deleted</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      ) : null}
      {saved ? (
        <Alert>
          <AlertTitle>Skill updated</AlertTitle>
          <AlertDescription>Your changes have been saved.</AlertDescription>
        </Alert>
      ) : null}

      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        <SkillForm
          key={`${skill.id}:${skill.updated_at}`}
          cancelLabel="Back to skills"
          isSubmitting={updateSkillMutation.isPending}
          mode="edit"
          onChange={() => {
            if (saved) {
              setSaved(false)
            }
          }}
          onSubmit={handleUpdateSkill}
          skill={skill}
        >
          <SkillDocumentsSection skillId={skill.id} />
        </SkillForm>
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
