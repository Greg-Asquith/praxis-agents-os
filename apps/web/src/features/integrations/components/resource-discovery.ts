// apps/web/src/features/integrations/components/resource-discovery.ts

export function discoveryFinished(previousStatus: string, currentStatus: string) {
  return previousStatus === "discovery_pending" && currentStatus !== "discovery_pending"
}

export function discoveryStatusLabel(status: string) {
  if (status === "running") {
    return "Discovery in progress"
  }
  if (status === "succeeded") {
    return "Discovery completed"
  }
  if (status === "failed") {
    return "Discovery failed"
  }
  return status
}
