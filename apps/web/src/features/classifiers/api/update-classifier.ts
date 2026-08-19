// apps/web/src/features/classifiers/api/update-classifier.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { invalidateClassifierQueries } from "@/features/classifiers/api/invalidate-classifier-queries"
import type { Classifier, ClassifierUpdateRequest } from "@/features/classifiers/types"
import { apiRequest } from "@/lib/api/client"

type UpdateClassifierInput = {
  classifierId: string
  payload: ClassifierUpdateRequest
}

async function updateClassifier({ classifierId, payload }: UpdateClassifierInput) {
  return apiRequest<Classifier>(`/classifiers/${classifierId}`, {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateClassifierMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateClassifier,
    onSuccess: async () => {
      await invalidateClassifierQueries(queryClient)
    },
  })
}
