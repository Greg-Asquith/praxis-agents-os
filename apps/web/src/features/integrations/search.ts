// apps/web/src/features/integrations/search.ts

export type IntegrationsSearch = {
  integration_error?: string
  integration_status?: "connected"
}

export function validateIntegrationsSearch(search: Record<string, unknown>): IntegrationsSearch {
  return {
    ...(typeof search["integration_error"] === "string"
      ? { integration_error: search["integration_error"] }
      : {}),
    ...(search["integration_status"] === "connected"
      ? { integration_status: "connected" as const }
      : {}),
  }
}
