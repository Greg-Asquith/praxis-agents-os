import { isRecord } from "@/lib/guards"

export type AuditDetailValue =
  string | number | boolean | null | AuditDetailValue[] | { [key: string]: AuditDetailValue }

type OperationTarget = {
  entity_type: string
  external_id: string
  display_name: string | null
  integration_resource_id: string | null
  attributes: Record<string, AuditDetailValue>
}

export type OperationChange = {
  action: string
  entity_type: string
  external_ref: string | null
  fields: Record<string, AuditDetailValue>
}

export type OperationDetail = {
  schema_version: 1
  target: OperationTarget
  changes: OperationChange[]
  counts: { applied: number; skipped: number; failed: number }
}

export function parseIntegrationOperationDetail(value: unknown): OperationDetail | null {
  if (!isRecord(value) || value["schema_version"] !== 1) return null
  const target = value["target"]
  const counts = value["counts"]
  const changes = value["changes"]
  if (
    !isRecord(target) ||
    typeof target["entity_type"] !== "string" ||
    typeof target["external_id"] !== "string" ||
    !(target["display_name"] === null || typeof target["display_name"] === "string") ||
    !(
      target["integration_resource_id"] === null ||
      typeof target["integration_resource_id"] === "string"
    ) ||
    !isDetailRecord(target["attributes"]) ||
    !isRecord(counts) ||
    !isCount(counts["applied"]) ||
    !isCount(counts["skipped"]) ||
    !isCount(counts["failed"]) ||
    !Array.isArray(changes)
  ) {
    return null
  }
  const parsedChanges: OperationChange[] = []
  for (const change of changes) {
    if (
      !isRecord(change) ||
      typeof change["action"] !== "string" ||
      typeof change["entity_type"] !== "string" ||
      !(change["external_ref"] === null || typeof change["external_ref"] === "string") ||
      !isDetailRecord(change["fields"])
    ) {
      return null
    }
    parsedChanges.push({
      action: change["action"],
      entity_type: change["entity_type"],
      external_ref: change["external_ref"],
      fields: change["fields"],
    })
  }
  return {
    schema_version: 1,
    target: {
      entity_type: target["entity_type"],
      external_id: target["external_id"],
      display_name: target["display_name"],
      integration_resource_id: target["integration_resource_id"],
      attributes: target["attributes"],
    },
    changes: parsedChanges,
    counts: {
      applied: counts["applied"],
      skipped: counts["skipped"],
      failed: counts["failed"],
    },
  }
}

function isDetailRecord(value: unknown): value is Record<string, AuditDetailValue> {
  return isRecord(value) && Object.values(value).every(isDetailValue)
}

function isDetailValue(value: unknown): value is AuditDetailValue {
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) return true
  if (Array.isArray(value)) return value.every(isDetailValue)
  return isDetailRecord(value)
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}
