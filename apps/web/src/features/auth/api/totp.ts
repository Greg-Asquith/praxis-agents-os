// apps/web/src/features/auth/api/totp.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import type { TotpEnableResponse, TotpSetupResponse } from "@/features/auth/types"

async function setupTotp(payload: { current_password?: string }) {
  return apiRequest<TotpSetupResponse>("/auth/totp/setup", { body: payload, method: "POST" })
}

async function enableTotp(payload: { enrollment_token: string; token: string }) {
  return apiRequest<TotpEnableResponse>("/auth/totp/enable", {
    body: payload,
    method: "POST",
  })
}

async function disableTotp(code: { token?: string; backup_code?: string }) {
  return apiRequest<{ message: string }>("/auth/totp", {
    body: code,
    method: "DELETE",
  })
}

export function useSetupTotpMutation() {
  return useMutation({ mutationFn: setupTotp })
}

export function useEnableTotpMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: enableTotp,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: currentUserQueryOptions().queryKey })
    },
  })
}

export function useDisableTotpMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: disableTotp,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: currentUserQueryOptions().queryKey })
    },
  })
}
