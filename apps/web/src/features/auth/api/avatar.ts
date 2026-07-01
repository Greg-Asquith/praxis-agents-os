// apps/web/src/features/auth/api/avatar.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { currentUserQueryKey } from "@/features/auth/api/get-current-user"
import type { AuthUser } from "@/features/auth/types"
import { apiRequest } from "@/lib/api/client"
import type { AssetUploadGrant, AssetUploadRequest } from "@/lib/storage"

async function createAvatarUpload(payload: AssetUploadRequest) {
  return apiRequest<AssetUploadGrant>("/auth/me/avatar/upload", {
    body: payload,
    method: "POST",
  })
}

async function confirmAvatarUpload(uploadToken: string) {
  return apiRequest<AuthUser>("/auth/me/avatar/confirm", {
    body: { upload_token: uploadToken },
    method: "POST",
  })
}

async function deleteAvatar() {
  return apiRequest<AuthUser>("/auth/me/avatar", {
    method: "DELETE",
  })
}

export function useCreateAvatarUploadMutation() {
  return useMutation({
    mutationFn: createAvatarUpload,
  })
}

export function useConfirmAvatarUploadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: confirmAvatarUpload,
    onSuccess: (user) => {
      queryClient.setQueryData(currentUserQueryKey, user)
    },
  })
}

export function useDeleteAvatarMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteAvatar,
    onSuccess: (user) => {
      queryClient.setQueryData(currentUserQueryKey, user)
    },
  })
}
