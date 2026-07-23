// apps/web/src/features/integrations/format.ts

import type { IntegrationProvider } from "@/features/integrations/types"
import { formatGoogleAdsAccountId, titleCaseToken } from "@/lib/format"

export function integrationOwnershipDescription(ownerScope: IntegrationProvider["owner_scope"]) {
  return ownerScope === "user" ? "Only you can manage this" : "Shared with the workspace"
}

export function integrationAuthModeLabel(authMode: string) {
  if (authMode === "oauth") {
    return "Sign In With Google"
  }
  if (authMode === "api_key") {
    return "API key"
  }
  if (authMode === "service_account") {
    return "Service Account Ley"
  }
  return titleCaseToken(authMode, "Sign In Method")
}

export function integrationResourceTypeLabel(resourceType: string) {
  return titleCaseToken(resourceType, "Resources")
}

export function formatIntegrationResourceValue(
  providerKey: string | undefined,
  value: string
): string {
  return providerKey === "google_ads" ? formatGoogleAdsAccountId(value) : value
}
