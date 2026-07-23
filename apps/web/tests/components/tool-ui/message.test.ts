import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { MessageListRow } from "@/components/tool-ui/message"

describe("MessageListRow", () => {
  it("wraps long message text within the available width", () => {
    const html = renderToStaticMarkup(
      createElement(MessageListRow, {
        date: "1d ago",
        sender: "averylongsenderaddresswithoutnaturalbreaks@example.com",
        snippet: "A long preview that should stay inside the message row.",
        subject: "averylongsubjectwithoutnaturalbreaks",
      })
    )

    expect(html).toContain("w-full min-w-0")
    expect(html).toMatch(/class="[^"]*min-w-0[^"]*flex-1[^"]*wrap-break-word[^"]*"/)
    expect(html.match(/wrap-break-word/g)).toHaveLength(3)
    expect(html).not.toContain("truncate")
  })
})
