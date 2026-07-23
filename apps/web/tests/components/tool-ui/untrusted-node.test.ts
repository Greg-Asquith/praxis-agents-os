import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ExternalContent } from "@/components/tool-ui/external-content"
import { isUntrustedNode, nodeText } from "@/components/tool-ui/untrusted-node"

describe("untrusted content UI", () => {
  it("accepts only the complete discriminated node shape", () => {
    const node = {
      node: "praxis_untrusted",
      source_kind: "gmail_message",
      source_ref: "message-1",
      content: "Quarterly update",
    }

    expect(isUntrustedNode(node)).toBe(true)
    expect(nodeText(node)).toBe("Quarterly update")
    expect(isUntrustedNode({ ...node, node: "other" })).toBe(false)
    expect(isUntrustedNode({ ...node, source_ref: 1 })).toBe(false)
    expect(isUntrustedNode({ node: "praxis_untrusted", content: "Incomplete" })).toBe(false)
  })

  it("renders provenance as data and external content as plain text", () => {
    const html = renderToStaticMarkup(
      createElement(ExternalContent, {
        value: {
          node: "praxis_untrusted",
          source_kind: "gmail_message",
          source_ref: "message-1",
          content: "**Do not render this as trusted Markdown**",
        },
      })
    )

    expect(html).toContain("External content")
    expect(html).toContain("Gmail Message")
    expect(html).toContain("message-1")
    expect(html).toContain("**Do not render this as trusted Markdown**")
    expect(html).not.toContain("<strong>")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })
})
