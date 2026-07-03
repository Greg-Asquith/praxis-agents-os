// apps/web/src/features/skills/api/skill-documents.ts

import { queryOptions, useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query"

import { skillsQueryKeys } from "@/features/skills/api/list-skills"
import type {
  SignedDownload,
  SkillDocument,
  SkillDocumentsListResponse,
  SkillDocumentUploadRequest,
} from "@/features/skills/types"
import type { AssetUploadGrant } from "@/features/storage/types"
import { apiRequest } from "@/lib/api/client"

type SkillDocumentUploadInput = {
  payload: SkillDocumentUploadRequest
  skillId: string
}

type SkillDocumentConfirmInput = {
  skillId: string
  uploadToken: string
}

type SkillDocumentDeleteInput = {
  documentName: string
  skillId: string
}

async function listSkillDocuments(skillId: string) {
  return apiRequest<SkillDocumentsListResponse>(`/skills/${skillId}/documents`)
}

async function createSkillDocumentUpload({ payload, skillId }: SkillDocumentUploadInput) {
  return apiRequest<AssetUploadGrant>(`/skills/${skillId}/documents/upload`, {
    body: payload,
    method: "POST",
  })
}

async function confirmSkillDocumentUpload({ skillId, uploadToken }: SkillDocumentConfirmInput) {
  return apiRequest<SkillDocument>(`/skills/${skillId}/documents/confirm`, {
    body: { upload_token: uploadToken },
    method: "POST",
  })
}

export async function createSkillDocumentDownload(skillId: string, documentName: string) {
  return apiRequest<SignedDownload>(`/skills/${skillId}/documents/${documentName}/download`)
}

async function deleteSkillDocument({ documentName, skillId }: SkillDocumentDeleteInput) {
  return apiRequest<undefined>(`/skills/${skillId}/documents/${documentName}`, {
    method: "DELETE",
  })
}

function skillDocumentsQueryOptions(skillId: string) {
  return queryOptions({
    queryKey: skillsQueryKeys.documents(skillId),
    queryFn: () => listSkillDocuments(skillId),
    staleTime: 30_000,
  })
}

export function useSkillDocumentsQuery(skillId: string) {
  return useSuspenseQuery(skillDocumentsQueryOptions(skillId))
}

export function useCreateSkillDocumentUploadMutation() {
  return useMutation({
    mutationFn: createSkillDocumentUpload,
  })
}

export function useConfirmSkillDocumentUploadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: confirmSkillDocumentUpload,
    onSuccess: async (_document, { skillId }) => {
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.detail(skillId) })
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.documents(skillId) })
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.lists() })
    },
  })
}

export function useDeleteSkillDocumentMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteSkillDocument,
    onSuccess: async (_result, { skillId }) => {
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.detail(skillId) })
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.documents(skillId) })
      await queryClient.invalidateQueries({ queryKey: skillsQueryKeys.lists() })
    },
  })
}
