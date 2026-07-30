import { describe, expect, it } from "vitest"

import { buildHtmlFrameDocument, INTERACTIVE_HTML_FRAME_CSP } from "@/lib/html-frame-document"

describe("buildHtmlFrameDocument", () => {
  it("places the CSP before untrusted content", () => {
    const content = "<script>fetch('https://example.com')</script>"
    const document = buildHtmlFrameDocument({
      content,
      contentSecurityPolicy: INTERACTIVE_HTML_FRAME_CSP,
    })

    expect(document).toContain(
      `<meta http-equiv="Content-Security-Policy" content="${INTERACTIVE_HTML_FRAME_CSP}">`
    )
    expect(document.indexOf("Content-Security-Policy")).toBeLessThan(document.indexOf(content))
    expect(INTERACTIVE_HTML_FRAME_CSP).toContain("connect-src 'none'")
  })
})
