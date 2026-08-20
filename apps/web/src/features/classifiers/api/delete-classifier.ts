// apps/web/src/features/classifiers/api/delete-classifier.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { invalidateClassifierQueries } from "@/features/classifiers/api/invalidate-classifier-queries"
import { apiRequestNoContent } from "@/lib/api/client"

async function deleteClassifier(classifierId: string) {
  return apiRequestNoContent(`/classifiers/${classifierId}`, {
    method: "DELETE",
  })
}

export function useDeleteClassifierMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteClassifier,
    onSuccess: async () => {
      await invalidateClassifierQueries(queryClient)
    },
  })
}
