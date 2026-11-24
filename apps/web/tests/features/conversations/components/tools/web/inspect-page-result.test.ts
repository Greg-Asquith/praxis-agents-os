// apps/web/tests/features/conversations/components/tools/web/inspect-page-result.test.ts

import { describe, expect, it } from "vitest"

import { inspectPageResult } from "@/features/conversations/components/tools/web/inspect-page-result"

function node(content: string) {
  return { node: "praxis_untrusted", source_kind: "web_fetch", source_ref: "ref", content }
}

function result(fields: Record<string, unknown>) {
  return {
    requested_url: "https://a.example/",
    final_url: node("https://a.example/"),
    status: 200,
    redirects: [],
    blocked_by_site: false,
    user_agent: "praxis",
    content_type: node("text/html"),
    fetched_at: "2026-11-23T10:00:00+00:00",
    headers: null,
    page: null,
    sitemap: null,
    robots: null,
    ...fields,
  }
}

describe("inspectPageResult", () => {
  it("keeps only http(s) links and rejects a final URL that isn't http(s)", () => {
    const links = {
      total: 2,
      internal: 1,
      external: 1,
      nofollow: 0,
      items: [
        { url: node("https://a.example/b"), text: node("B"), internal: true, nofollow: false },
        { url: node("javascript:alert(1)"), text: null, internal: false, nofollow: false },
      ],
    }
    const page = {
      word_count: 12,
      looks_client_rendered: false,
      meta: null,
      headings: null,
      links,
      images: null,
      structured_data: null,
      tags: null,
    }

    const parsed = inspectPageResult(result({ kind: "page", page }))

    expect(parsed?.page?.links?.items.map((link) => link.url)).toEqual(["https://a.example/b"])
    expect(inspectPageResult(result({ kind: "page", final_url: node("javascript:x") }))).toBeNull()
  })

  it("reads a sitemap index and drops entries without an address", () => {
    const sitemap = {
      type: "sitemapindex",
      total: 3,
      entries: [
        { loc: node("https://a.example/posts.xml"), lastmod: "2026-11-01" },
        { loc: null, lastmod: "2026-11-02" },
        { loc: node("https://a.example/pages.xml"), lastmod: 7 },
      ],
    }

    const parsed = inspectPageResult(result({ kind: "sitemap", sitemap }))

    expect(parsed?.sitemap).toEqual({
      entries: [
        { lastmod: "2026-11-01", loc: "https://a.example/posts.xml" },
        { lastmod: null, loc: "https://a.example/pages.xml" },
      ],
      index: true,
      total: 3,
    })
  })

  it("reads robots.txt groups and sitemaps as plain text", () => {
    const robots = {
      groups: [
        {
          user_agents: [node("*")],
          allow: [node("/public")],
          disallow: [node("/admin"), 42],
          crawl_delay: "10",
        },
      ],
      sitemaps: [node("https://a.example/sitemap.xml")],
    }

    const parsed = inspectPageResult(result({ kind: "robots", robots }))

    expect(parsed?.robots).toEqual({
      groups: [{ allow: ["/public"], crawlDelay: null, disallow: ["/admin"], userAgents: ["*"] }],
      sitemaps: ["https://a.example/sitemap.xml"],
    })
  })
})
