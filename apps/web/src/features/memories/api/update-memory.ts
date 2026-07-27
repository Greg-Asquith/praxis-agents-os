// apps/web/src/features/memories/api/update-memory.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { memoriesQueryKeys } from "@/features/memories/api/list-memories"
import type { Memory, MemoryUpdateRequest } from "@/features/memories/types"
import { apiRequest } from "@/lib/api/client"

type UpdateMemoryInput = {
  memoryId: string
  payload: MemoryUpdateRequest
}

export function useUpdateMemoryMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ memoryId, payload }: UpdateMemoryInput) =>
      apiRequest<Memory>(`/memories/${memoryId}`, {
        body: payload,
        method: "PATCH",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: memoriesQueryKeys.workspace() })
    },
  })
}
