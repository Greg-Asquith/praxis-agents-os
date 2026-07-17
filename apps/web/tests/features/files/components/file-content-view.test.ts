import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { FileContentView } from "@/features/files/components/file-content-view"

describe("FileContentView", () => {
  it("allows scripts in HTML previews without granting same-origin access", () => {
    const markup = renderToStaticMarkup(
      createElement(FileContentView, {
        content: "<script>document.body.textContent = 'Rendered'</script>",
        mediaType: "text/html",
        name: "preview.html",
      })
    )

    expect(markup).toContain('sandbox="allow-scripts"')
    expect(markup).not.toContain("allow-same-origin")
  })
})
