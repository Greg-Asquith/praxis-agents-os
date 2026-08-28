// apps/web/src/features/knowledge/components/integration-import-form-model.ts

import type {
  IntegrationConnection,
  IntegrationProvider,
  IntegrationResource,
} from "@/features/integrations/types"
import type {
  KbIntegrationDocumentCreateRequest,
  KbIntegrationSourceReference,
} from "@/features/knowledge/types"
import type { FormValidationEntry } from "@/lib/forms"

const UNUSABLE_CONNECTION_STATUSES = new Set([
  "auth_pending",
  "needs_credential",
  "needs_reauth",
  "revoked",
])

export const INTEGRATION_IMPORT_IS_PRIVATE_DEFAULT = true

export type IntegrationImportResourceState = "loading" | "error" | "empty" | "ready"

export type KnowledgeSourceProviderOption = {
  provider: IntegrationProvider
  connections: IntegrationConnection[]
}

export type IntegrationImportFormState = {
  integrationResourceId: string
  isPrivate: boolean
  source: string | KbIntegrationSourceReference
  title: string
}

export function eligibleKnowledgeSourceProviders(
  providers: readonly IntegrationProvider[],
  connections: readonly IntegrationConnection[],
  currentUserId: string
): KnowledgeSourceProviderOption[] {
  return providers.flatMap((provider) => {
    if (!provider.knowledge_source_supported) {
      return []
    }
    const eligibleConnections = connections.filter(
      (connection) =>
        connection.provider_key === provider.provider_key &&
        connection.owner_user_id === currentUserId &&
        !UNUSABLE_CONNECTION_STATUSES.has(connection.status)
    )
    return eligibleConnections.length > 0 ? [{ provider, connections: eligibleConnections }] : []
  })
}

export function availableKnowledgeSourceResources(
  resources: readonly IntegrationResource[],
  supportedResourceTypes: readonly string[]
): IntegrationResource[] {
  const supported = new Set(supportedResourceTypes)
  return resources.filter(
    (resource) =>
      supported.has(resource.resource_type) &&
      resource.availability === "available" &&
      resource.removed_at === null
  )
}

export function integrationImportResourceState({
  hasError,
  isLoading,
  resourceCount,
}: {
  hasError: boolean
  isLoading: boolean
  resourceCount: number
}): IntegrationImportResourceState {
  if (isLoading) {
    return "loading"
  }
  if (hasError) {
    return "error"
  }
  return resourceCount === 0 ? "empty" : "ready"
}

export function integrationImportErrorMessage(message: string): string {
  return message.split(" | ", 1)[0] ?? message
}

export function validateIntegrationImportForm(
  state: IntegrationImportFormState
): FormValidationEntry[] {
  const entries: FormValidationEntry[] = []
  if (!state.integrationResourceId) {
    entries.push({
      fieldId: "knowledge-integration-resource",
      label: "Workspace",
      message: "Choose a connected workspace.",
    })
  }
  const title = state.title.trim()
  if (title.length > 500) {
    entries.push({
      fieldId: "knowledge-integration-title",
      label: "Title",
      message: "Title must be 500 characters or fewer.",
    })
  }
  if (typeof state.source === "string") {
    const source = state.source.trim()
    try {
      const parsed = new URL(source)
      if (parsed.protocol !== "https:") {
        throw new Error("unsupported protocol")
      }
    } catch {
      entries.push({
        fieldId: "knowledge-integration-url",
        label: "Page URL",
        message: "Enter a valid HTTPS URL.",
      })
    }
  }
  return entries
}

export function buildIntegrationImportPayload(
  state: IntegrationImportFormState
): KbIntegrationDocumentCreateRequest | FormValidationEntry[] {
  const validation = validateIntegrationImportForm(state)
  if (validation.length > 0) {
    return validation
  }
  const title = state.title.trim()
  return {
    integration_resource_id: state.integrationResourceId,
    is_private: state.isPrivate,
    source: typeof state.source === "string" ? state.source.trim() : state.source,
    ...(title ? { title } : {}),
  }
}
