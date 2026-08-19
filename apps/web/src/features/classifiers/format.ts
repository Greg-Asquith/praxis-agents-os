// apps/web/src/features/classifiers/format.ts

import type { Classifier } from "@/features/classifiers/types"
import type { ModelCatalogResponse } from "@/features/models/types"

export function classifierModelLabel(
  classifier: Pick<Classifier, "model" | "model_provider">,
  catalog: ModelCatalogResponse
) {
  if (!classifier.model_provider || !classifier.model) {
    return "Automatic"
  }
  const qualifiedId = `${classifier.model_provider}:${classifier.model}`
  const model = catalog.models.find((entry) => entry.id === qualifiedId)
  const provider = catalog.providers.find((entry) => entry.provider === classifier.model_provider)
  if (!model) {
    return qualifiedId
  }
  return `${provider?.display_name ?? classifier.model_provider} · ${model.display_name}`
}
