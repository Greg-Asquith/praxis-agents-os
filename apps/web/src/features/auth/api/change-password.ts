// apps/web/src/features/auth/api/change-password.ts

import { useMutation } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { ChangePasswordRequest } from "@/features/auth/types"

async function changePassword(payload: ChangePasswordRequest) {
  return apiRequest<{ message: string }>("/auth/password", {
    body: payload,
    method: "PUT",
  })
}

export function useChangePasswordMutation() {
  return useMutation({
    mutationFn: changePassword,
  })
}
