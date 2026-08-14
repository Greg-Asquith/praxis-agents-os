// apps/web/src/features/conversations/native-tools/artifact-tools.ts

import type { ArtifactType } from "@/features/artifacts/types"
import {
  isDateTimeString,
  isNonNegativeInteger,
  isNullableString,
  isPositiveInteger,
  isRecord,
} from "@/lib/guards"

export const CREATE_ARTIFACT_TOOL_NAME = "create_artifact"
export const LIST_ARTIFACTS_TOOL_NAME = "list_artifacts"
export const READ_ARTIFACT_TOOL_NAME = "read_artifact"
export const UPDATE_ARTIFACT_TOOL_NAME = "update_artifact"

export type ArtifactReference = {
  version: 1
  entity_kind: "artifact"
  entity_id: string
  label: string
  description: string | null
  scope_label: string | null
}

export type ArtifactToolResult = {
  artifact_id: string
  version_id: string
  title: string
  artifact_type: ArtifactType
}

export type ArtifactToolSummary = {
  id: string
  reference: ArtifactReference
  title: string
  artifact_type: ArtifactType
  version_count: number
  updated_at: string
  conversation_id: string | null
}

export type ArtifactListToolResult = {
  items: ArtifactToolSummary[]
  total: number
  returned: number
}

export type ArtifactReadToolResult = {
  id: string
  reference: ArtifactReference
  title: string
  artifact_type: ArtifactType
  revision_number: number
  updated_at: string
  content: string | null
  truncated: boolean
  size_bytes: number
  content_type: string
}

export function artifactToolResult(value: unknown): ArtifactToolResult | null {
  if (
    !isRecord(value) ||
    typeof value["artifact_id"] !== "string" ||
    typeof value["version_id"] !== "string" ||
    typeof value["title"] !== "string" ||
    !isCreatableArtifactType(value["artifact_type"])
  ) {
    return null
  }
  return {
    artifact_id: value["artifact_id"],
    version_id: value["version_id"],
    title: value["title"],
    artifact_type: value["artifact_type"],
  }
}

export function artifactListToolResult(value: unknown): ArtifactListToolResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["items"]) ||
    !isNonNegativeInteger(value["total"]) ||
    !isNonNegativeInteger(value["returned"]) ||
    value["returned"] !== value["items"].length ||
    value["returned"] > value["total"]
  ) {
    return null
  }
  const items = value["items"].map(artifactToolSummary)
  if (items.some((item) => item === null)) {
    return null
  }
  return {
    items: items as ArtifactToolSummary[],
    total: value["total"],
    returned: value["returned"],
  }
}

export function artifactReadToolResult(value: unknown): ArtifactReadToolResult | null {
  if (
    !isRecord(value) ||
    typeof value["id"] !== "string" ||
    typeof value["title"] !== "string" ||
    !isArtifactType(value["artifact_type"]) ||
    !isPositiveInteger(value["revision_number"]) ||
    !isDateTimeString(value["updated_at"]) ||
    !isNullableString(value["content"]) ||
    typeof value["truncated"] !== "boolean" ||
    !isNonNegativeInteger(value["size_bytes"]) ||
    typeof value["content_type"] !== "string"
  ) {
    return null
  }
  const reference = artifactReference(value["reference"])
  if (
    reference?.entity_id !== value["id"] ||
    (value["artifact_type"] === "image-ref") !== (value["content"] === null) ||
    (value["content"] === null && value["truncated"])
  ) {
    return null
  }
  return {
    id: value["id"],
    reference,
    title: value["title"],
    artifact_type: value["artifact_type"],
    revision_number: value["revision_number"],
    updated_at: value["updated_at"],
    content: value["content"],
    truncated: value["truncated"],
    size_bytes: value["size_bytes"],
    content_type: value["content_type"],
  }
}

export function artifactSearchArg(value: unknown): string | null {
  if (!isRecord(value) || typeof value["search"] !== "string" || !value["search"].trim()) {
    return null
  }
  return value["search"].trim()
}

export function artifactReferenceArg(value: unknown): ArtifactReference | null {
  return isRecord(value) ? artifactReference(value["artifact_id"]) : null
}

export function artifactTitleArg(value: unknown): string | null {
  if (!isRecord(value) || typeof value["title"] !== "string" || !value["title"].trim()) {
    return null
  }
  return value["title"]
}

function artifactToolSummary(value: unknown): ArtifactToolSummary | null {
  if (
    !isRecord(value) ||
    typeof value["id"] !== "string" ||
    typeof value["title"] !== "string" ||
    !isArtifactType(value["artifact_type"]) ||
    !isPositiveInteger(value["version_count"]) ||
    !isDateTimeString(value["updated_at"]) ||
    !isNullableString(value["conversation_id"])
  ) {
    return null
  }
  const reference = artifactReference(value["reference"])
  if (reference?.entity_id !== value["id"]) {
    return null
  }
  return {
    id: value["id"],
    reference,
    title: value["title"],
    artifact_type: value["artifact_type"],
    version_count: value["version_count"],
    updated_at: value["updated_at"],
    conversation_id: value["conversation_id"],
  }
}

function artifactReference(value: unknown): ArtifactReference | null {
  if (
    !isRecord(value) ||
    value["version"] !== 1 ||
    value["entity_kind"] !== "artifact" ||
    typeof value["entity_id"] !== "string" ||
    typeof value["label"] !== "string" ||
    !isNullableString(value["description"]) ||
    !isNullableString(value["scope_label"])
  ) {
    return null
  }
  return {
    version: 1,
    entity_kind: "artifact",
    entity_id: value["entity_id"],
    label: value["label"],
    description: value["description"],
    scope_label: value["scope_label"],
  }
}

function isArtifactType(value: unknown): value is ArtifactType {
  return isCreatableArtifactType(value) || value === "image-ref"
}

function isCreatableArtifactType(value: unknown): value is Exclude<ArtifactType, "image-ref"> {
  return value === "html" || value === "markdown" || value === "mermaid" || value === "csv"
}
