// apps/web/src/features/integrations/format.ts

import type { IntegrationProvider } from "@/features/integrations/types"
import { titleCaseToken } from "@/lib/format"

export function integrationOwnerScopeLabel(ownerScope: IntegrationProvider["owner_scope"]) {
  return ownerScope === "user" ? "Your Account" : "Workspace"
}

export function integrationAuthModeLabel(authMode: string) {
  if (authMode === "oauth") {
    return "OAuth Sign In"
  }
  if (authMode === "api_key") {
    return "API key"
  }
  return titleCaseToken(authMode, "Connection")
}

export function integrationResourceTypeLabel(resourceType: string) {
  return titleCaseToken(resourceType, "Resources")
}
