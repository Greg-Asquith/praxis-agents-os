import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ArtifactPreviewFrame } from "@/features/artifacts/components/artifact-preview-frame"

describe("ArtifactPreviewFrame", () => {
  it("keeps HTML previews on an opaque sandboxed origin", () => {
    const markup = renderToStaticMarkup(
      createElement(ArtifactPreviewFrame, {
        artifactType: "html",
        content: {
          content: "<script>document.body.textContent = 'Rendered'</script>",
          content_type: "text/html",
          download_url: null,
          size_bytes: 55,
        },
        title: "HTML artifact",
        versionId: "version-1",
      })
    )

    expect(markup).toContain('sandbox="allow-scripts"')
    expect(markup).not.toContain("allow-same-origin")
    expect(markup).toContain("Content-Security-Policy")
    expect(markup).toContain("connect-src &#x27;none&#x27;")
  })

  it("falls back to plain text for oversized markdown", () => {
    const markup = renderToStaticMarkup(
      createElement(ArtifactPreviewFrame, {
        artifactType: "markdown",
        content: {
          content: "#".repeat(200_001),
          content_type: "text/markdown",
          download_url: null,
          size_bytes: 200_001,
        },
        title: "Large artifact",
        versionId: "version-1",
      })
    )

    expect(markup).toContain("<pre")
  })

  it("preserves quoted newlines and escaped quotes in CSV cells", () => {
    const markup = renderToStaticMarkup(
      createElement(ArtifactPreviewFrame, {
        artifactType: "csv",
        content: {
          content: 'name,notes\r\nPraxis,"first line\nsecond ""quoted"" line"',
          content_type: "text/csv",
          download_url: null,
          size_bytes: 57,
        },
        title: "CSV artifact",
        versionId: "version-1",
      })
    )

    expect(markup).toContain("first line\nsecond &quot;quoted&quot; line")
  })

  it("gives each HTML artifact version a distinct iframe identity", () => {
    const content = {
      content: "<p>Preview</p>",
      content_type: "text/html",
      download_url: null,
      size_bytes: 14,
    }

    const firstFrame = ArtifactPreviewFrame({
      artifactType: "html",
      content,
      title: "HTML artifact",
      versionId: "version-1",
    })
    const secondFrame = ArtifactPreviewFrame({
      artifactType: "html",
      content,
      title: "HTML artifact",
      versionId: "version-2",
    })

    expect(firstFrame.key).toBe("version-1")
    expect(secondFrame.key).toBe("version-2")
  })
})
