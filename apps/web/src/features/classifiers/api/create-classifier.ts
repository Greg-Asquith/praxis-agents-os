// apps/web/src/features/classifiers/api/create-classifier.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { invalidateClassifierQueries } from "@/features/classifiers/api/invalidate-classifier-queries"
import type { Classifier, ClassifierCreateRequest } from "@/features/classifiers/types"
import { apiRequest } from "@/lib/api/client"

async function createClassifier(payload: ClassifierCreateRequest) {
  return apiRequest<Classifier>("/classifiers/", {
    body: payload,
    method: "POST",
  })
}

export function useCreateClassifierMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createClassifier,
    onSuccess: async () => {
      await invalidateClassifierQueries(queryClient)
    },
  })
}
