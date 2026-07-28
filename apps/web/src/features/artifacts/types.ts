// apps/web/src/features/artifacts/types.ts

export type ArtifactType = "html" | "markdown" | "mermaid" | "csv"

export type ArtifactViewGrant = {
  url: string
  expires_at: string
}
