// apps/web/tests/features/conversations/components/tools/web/web-redirects.test.ts

import { describe, expect, it } from "vitest"

import { webRedirects } from "@/features/conversations/components/tools/web/web-redirects"

function node(content: string) {
  return { node: "praxis_untrusted", source_kind: "web_fetch", source_ref: "ref", content }
}

describe("webRedirects", () => {
  it("refuses the whole chain when one hop is malformed", () => {
    const good = { status: 301, location: node("https://a.example/new") }

    expect(webRedirects([good])).toEqual([{ location: "https://a.example/new", status: 301 }])
    expect(webRedirects([good, { status: 302 }])).toBeNull()
    expect(webRedirects([good, { status: -1, location: node("/x") }])).toBeNull()
  })
})
