import { describe, expect, it, vi } from "vitest"

import { ApiError } from "@/lib/api/errors"
import {
  artifactHrefForFailedFileDownload,
  workspaceFileIdFromHref,
} from "@/features/conversations/file-links"

const FILE_ID = "245de7d6-0963-4ba4-9b63-45fe64526252"

describe("workspaceFileIdFromHref", () => {
  it("accepts only the internal workspace-file route with a UUID", () => {
    expect(workspaceFileIdFromHref(`/files?fileId=${FILE_ID}`)).toBe(FILE_ID)
    expect(workspaceFileIdFromHref(`/files?page=2&fileId=${FILE_ID}`)).toBe(FILE_ID)
  })

  it("accepts model-rewritten absolute forms of the internal route", () => {
    expect(workspaceFileIdFromHref(`https://files?fileId=${FILE_ID}`)).toBe(FILE_ID)
    expect(workspaceFileIdFromHref(`https://files/?fileId=${FILE_ID}`)).toBe(FILE_ID)
    expect(workspaceFileIdFromHref(`files?fileId=${FILE_ID}`)).toBe(FILE_ID)
  })

  it("accepts the app origin but not other hosts serving /files", () => {
    vi.stubGlobal("window", { location: { origin: "https://app.example.test" } })
    try {
      expect(workspaceFileIdFromHref(`https://app.example.test/files?fileId=${FILE_ID}`)).toBe(
        FILE_ID
      )
      expect(workspaceFileIdFromHref(`https://example.com/files?fileId=${FILE_ID}`)).toBeNull()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("does not intercept malformed or external links", () => {
    expect(workspaceFileIdFromHref("/files?fileId=not-a-uuid")).toBeNull()
    expect(workspaceFileIdFromHref(`/artifacts/${FILE_ID}`)).toBeNull()
    expect(workspaceFileIdFromHref(`https://example.com/files?fileId=${FILE_ID}`)).toBeNull()
    expect(workspaceFileIdFromHref(`https://files/other?fileId=${FILE_ID}`)).toBeNull()
    expect(workspaceFileIdFromHref(`mailto:files?fileId=${FILE_ID}`)).toBeNull()
    expect(workspaceFileIdFromHref("http://[bad")).toBeNull()
  })
})

describe("artifactHrefForFailedFileDownload", () => {
  it("returns the artifact page after a missing file resolves as an artifact", async () => {
    const loadArtifact = vi.fn().mockResolvedValue({ id: FILE_ID })

    await expect(
      artifactHrefForFailedFileDownload(FILE_ID, apiError(404), loadArtifact)
    ).resolves.toBe(`/artifacts/${FILE_ID}`)
    expect(loadArtifact).toHaveBeenCalledWith(FILE_ID)
  })

  it("preserves file errors that do not resolve as artifacts", async () => {
    const loadArtifact = vi.fn().mockRejectedValue(apiError(404))

    await expect(
      artifactHrefForFailedFileDownload(FILE_ID, apiError(404), loadArtifact)
    ).resolves.toBeNull()
    await expect(
      artifactHrefForFailedFileDownload(FILE_ID, apiError(403), loadArtifact)
    ).resolves.toBeNull()
    expect(loadArtifact).toHaveBeenCalledTimes(1)
  })
})

function apiError(status: number) {
  return new ApiError({ status, message: "Request failed", problem: null })
}
