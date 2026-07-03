// apps/web/src/features/skills/routes/new-skill-route.tsx

import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeftIcon } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { useCreateSkillMutation } from "@/features/skills/api/create-skill"
import {
  useConfirmSkillDocumentUploadMutation,
  useCreateSkillDocumentUploadMutation,
} from "@/features/skills/api/skill-documents"
import { SkillForm, type PendingSkillDocumentUpload } from "@/features/skills/components/skill-form"
import type { SkillCreateRequest } from "@/features/skills/types"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForFile } from "@/lib/file"

export function NewSkillRoute() {
  const navigate = useNavigate()
  const createSkillMutation = useCreateSkillMutation()
  const createDocumentUploadMutation = useCreateSkillDocumentUploadMutation()
  const confirmDocumentUploadMutation = useConfirmSkillDocumentUploadMutation()
  const [isUploadingDocuments, setIsUploadingDocuments] = useState(false)
  const isSubmitting =
    createSkillMutation.isPending ||
    createDocumentUploadMutation.isPending ||
    confirmDocumentUploadMutation.isPending ||
    isUploadingDocuments

  async function handleCreateSkill(
    payload: SkillCreateRequest,
    documents: PendingSkillDocumentUpload[]
  ) {
    const skill = await createSkillMutation.mutateAsync(payload)
    if (documents.length > 0) {
      try {
        const failedConversions = await uploadPendingDocuments(skill.id, documents)
        if (failedConversions.length > 0) {
          window.alert(`Skill created, but conversion failed for: ${failedConversions.join(", ")}`)
        }
      } catch (uploadError) {
        window.alert(`Skill created, but document upload failed: ${getErrorMessage(uploadError)}`)
      }
    }
    await navigate({ to: "/skills/$skillId", params: { skillId: skill.id } })
  }

  async function uploadPendingDocuments(skillId: string, documents: PendingSkillDocumentUpload[]) {
    const failedConversions: string[] = []
    setIsUploadingDocuments(true)

    try {
      for (const document of documents) {
        const uploadGrant = await createDocumentUploadMutation.mutateAsync({
          skillId,
          payload: {
            content_type: contentTypeForFile(document.file),
            document_name: document.documentName,
            filename: document.file.name || document.documentName,
            size_bytes: document.file.size,
          },
        })
        await uploadFileDirectly(uploadGrant.upload, document.file, uploadGrant.max_size_bytes)
        const confirmedDocument = await confirmDocumentUploadMutation.mutateAsync({
          skillId,
          uploadToken: uploadGrant.upload_token,
        })
        if (confirmedDocument.status === "failed") {
          failedConversions.push(confirmedDocument.name)
        }
      }
    } finally {
      setIsUploadingDocuments(false)
    }

    return failedConversions
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Button className="w-fit" size="sm" variant="outline" render={<Link to="/skills" />}>
          <ArrowLeftIcon data-icon="inline-start" />
          Skills
        </Button>
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Agent runtime</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">New skill</h1>
          <p className="text-muted-foreground max-w-3xl text-sm">
            Package reusable instructions and reference documents agents can activate on demand.
          </p>
        </div>
      </div>

      <SkillForm
        cancelLabel="Cancel"
        isSubmitting={isSubmitting}
        mode="create"
        onSubmit={handleCreateSkill}
      />
    </div>
  )
}
