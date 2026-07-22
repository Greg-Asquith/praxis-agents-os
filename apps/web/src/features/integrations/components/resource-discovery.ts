// apps/web/src/features/integrations/components/resource-discovery.ts

export function discoveryFinished(previousStatus: string, currentStatus: string) {
  return previousStatus === "discovery_pending" && currentStatus !== "discovery_pending"
}

export function discoveryStatusLabel(status: string) {
  if (status === "running") {
    return "Looking for resources…"
  }
  if (status === "succeeded") {
    return "Resources are up to date"
  }
  if (status === "failed") {
    return "Resources could not be checked"
  }
  return status
}
