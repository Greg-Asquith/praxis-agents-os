// apps/web/src/features/auth/api/totp.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { currentUserQueryKey, currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import type {
  AuthResponse,
  TotpEnableResponse,
  TotpSetupResponse,
  TotpVerifyRequest,
} from "@/features/auth/types"

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

async function verifyTotp(payload: TotpVerifyRequest) {
  return apiRequest<AuthResponse>("/auth/totp/verify", {
    body: payload,
    method: "POST",
  })
}

export function totpVerificationRequest(code: string): TotpVerifyRequest {
  return code.length === 8 ? { backup_code: code } : { token: code }
}

export function verifyTotpMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: verifyTotp,
    onSuccess: async (response) => {
      if (response.user) {
        queryClient.setQueryData(currentUserQueryKey, response.user)
      }
      await queryClient.invalidateQueries({ queryKey: currentUserQueryOptions().queryKey })
    },
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

export function useVerifyTotpMutation() {
  const queryClient = useQueryClient()
  return useMutation(verifyTotpMutationOptions(queryClient))
}
