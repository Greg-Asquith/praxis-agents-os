// apps/web/tests/features/conversations/artifact-tools.test.ts

import { describe, expect, it } from "vitest"

import {
  artifactListToolResult,
  artifactReadToolResult,
  artifactReferenceArg,
  artifactSearchArg,
  artifactTitleArg,
  artifactToolResult,
} from "@/features/conversations/native-tools/artifact-tools"

describe("artifact tool payloads", () => {
  it("parses supported completed artifact results", () => {
    expect(
      artifactToolResult({
        artifact_id: "artifact-1",
        version_id: "version-1",
        title: "Quarterly report",
        artifact_type: "html",
      })
    ).toEqual({
      artifact_id: "artifact-1",
      version_id: "version-1",
      title: "Quarterly report",
      artifact_type: "html",
    })
  })

  it("rejects malformed results and reads pending titles", () => {
    expect(
      artifactToolResult({
        artifact_id: "artifact-1",
        version_id: "version-1",
        title: "Diagram",
        artifact_type: "image-ref",
      })
    ).toBeNull()
    expect(artifactTitleArg({ title: "Quarterly report" })).toBe("Quarterly report")
    expect(artifactTitleArg({ title: " " })).toBeNull()
  })

  it("parses bounded artifact discovery results with entity references", () => {
    expect(
      artifactListToolResult({
        items: [
          {
            id: "artifact-1",
            reference: artifactReference("artifact-1", "Quarterly report"),
            title: "Quarterly report",
            artifact_type: "markdown",
            version_count: 2,
            updated_at: "2026-08-14T10:00:00Z",
            conversation_id: "conversation-1",
          },
        ],
        total: 3,
        returned: 1,
      })
    ).toEqual({
      items: [
        {
          id: "artifact-1",
          reference: artifactReference("artifact-1", "Quarterly report"),
          title: "Quarterly report",
          artifact_type: "markdown",
          version_count: 2,
          updated_at: "2026-08-14T10:00:00Z",
          conversation_id: "conversation-1",
        },
      ],
      total: 3,
      returned: 1,
    })
    expect(
      artifactListToolResult({
        items: [
          {
            id: "artifact-1",
            reference: artifactReference("different-artifact", "Wrong"),
            title: "Quarterly report",
            artifact_type: "markdown",
            version_count: 2,
            updated_at: "2026-08-14T10:00:00Z",
            conversation_id: null,
          },
        ],
        total: 1,
        returned: 1,
      })
    ).toBeNull()
  })

  it("parses current artifact content and discovery arguments", () => {
    expect(
      artifactReadToolResult({
        id: "artifact-1",
        reference: artifactReference("artifact-1", "Quarterly report"),
        title: "Quarterly report",
        artifact_type: "markdown",
        revision_number: 3,
        updated_at: "2026-08-14T10:00:00Z",
        content: "# Report",
        truncated: false,
        size_bytes: 8,
        content_type: "text/markdown",
      })
    ).toMatchObject({ id: "artifact-1", content: "# Report", revision_number: 3 })
    expect(artifactSearchArg({ search: "  quarterly  " })).toBe("quarterly")
    expect(artifactSearchArg({ search: " " })).toBeNull()
    expect(
      artifactReferenceArg({ artifact_id: artifactReference("artifact-1", "Report") })
    ).toEqual(artifactReference("artifact-1", "Report"))
    expect(
      artifactReadToolResult({
        id: "artifact-1",
        reference: artifactReference("artifact-1", "Quarterly report"),
        title: "Quarterly report",
        artifact_type: "markdown",
        revision_number: 3,
        updated_at: "not-a-date",
        content: "# Report",
        truncated: false,
        size_bytes: 8,
        content_type: "text/markdown",
      })
    ).toBeNull()
  })
})

function artifactReference(entityId: string, label: string) {
  return {
    version: 1,
    entity_kind: "artifact",
    entity_id: entityId,
    label,
    description: "Markdown artifact",
    scope_label: null,
  }
}
