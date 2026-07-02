// apps/web/src/features/workspaces/api/workspace-icon.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { workspacesQueryKey } from "@/features/workspaces/api/list-workspaces"
import type { Workspace } from "@/features/workspaces/types"
import { apiRequest } from "@/lib/api/client"
import type { AssetUploadGrant, AssetUploadRequest } from "@/features/storage/types"

type WorkspaceIconUploadInput = {
  workspaceId: string
  payload: AssetUploadRequest
}

type WorkspaceIconConfirmInput = {
  workspaceId: string
  uploadToken: string
}

async function createWorkspaceIconUpload({ workspaceId, payload }: WorkspaceIconUploadInput) {
  return apiRequest<AssetUploadGrant>(`/workspaces/${workspaceId}/icon/upload`, {
    body: payload,
    method: "POST",
  })
}

async function confirmWorkspaceIconUpload({ workspaceId, uploadToken }: WorkspaceIconConfirmInput) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}/icon/confirm`, {
    body: { upload_token: uploadToken },
    method: "POST",
  })
}

async function deleteWorkspaceIcon(workspaceId: string) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}/icon`, {
    method: "DELETE",
  })
}

export function useCreateWorkspaceIconUploadMutation() {
  return useMutation({
    mutationFn: createWorkspaceIconUpload,
  })
}

export function useConfirmWorkspaceIconUploadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: confirmWorkspaceIconUpload,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
    },
  })
}

export function useDeleteWorkspaceIconMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteWorkspaceIcon,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
    },
  })
}
