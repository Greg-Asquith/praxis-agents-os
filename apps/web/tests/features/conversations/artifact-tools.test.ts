// apps/web/tests/features/conversations/artifact-tools.test.ts

import { describe, expect, it } from "vitest"

import {
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
})
