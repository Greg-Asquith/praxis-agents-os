// apps/web/src/features/skills/components/pending-skill-document-model.ts

export type PendingSkillDocumentUpload = {
  documentName: string
  file: File
  id: string
}

export type PendingSkillDocumentDraft = {
  documentName: string
  error: string | null
  file: File | null
  fileInputKey: number
}

export const EMPTY_PENDING_SKILL_DOCUMENT_DRAFT: PendingSkillDocumentDraft = {
  documentName: "",
  error: null,
  file: null,
  fileInputKey: 0,
}
