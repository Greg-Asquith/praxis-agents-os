// apps/web/src/features/conversations/native-tools/artifact-tools.ts

import type { ArtifactType } from "@/features/artifacts/types"
import { isRecord } from "@/lib/guards"

export const CREATE_ARTIFACT_TOOL_NAME = "create_artifact"
export const UPDATE_ARTIFACT_TOOL_NAME = "update_artifact"

export type ArtifactToolResult = {
  artifact_id: string
  version_id: string
  title: string
  artifact_type: ArtifactType
}

export function artifactToolResult(value: unknown): ArtifactToolResult | null {
  if (
    !isRecord(value) ||
    typeof value["artifact_id"] !== "string" ||
    typeof value["version_id"] !== "string" ||
    typeof value["title"] !== "string" ||
    !isArtifactType(value["artifact_type"])
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

export function artifactTitleArg(value: unknown): string | null {
  if (!isRecord(value) || typeof value["title"] !== "string" || !value["title"].trim()) {
    return null
  }
  return value["title"]
}

function isArtifactType(value: unknown): value is ArtifactType {
  return value === "html" || value === "markdown" || value === "mermaid" || value === "csv"
}
