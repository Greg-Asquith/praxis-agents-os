// apps/web/src/features/conversations/components/inspect-page-result.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { type WebRedirect, webRedirects } from "@/features/conversations/components/web-redirects"
import { isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export const INSPECT_PAGE_TOOL_NAME = "inspect_page"

type InspectedKind = "page" | "sitemap" | "robots" | "unsupported"

const KINDS: ReadonlySet<InspectedKind> = new Set(["page", "sitemap", "robots", "unsupported"])

export type PageMeta = {
  canonical: string | null
  description: string | null
  language: string | null
  metaRefresh: string | null
  robots: string | null
  title: string | null
  viewport: string | null
}

type PageTag = { category: string; foundIn: string; id: string | null; vendor: string }

export type StructuredDataBlock = {
  content: string
  truncated: boolean
  types: string[]
  valid: boolean
}

export type InspectedPage = {
  headings: { h1Count: number; items: { level: number; text: string | null }[] } | null
  images: {
    items: { alt: string | null; src: string | null }[]
    missingAlt: number
    total: number
  } | null
  links: {
    external: number
    internal: number
    items: { internal: boolean; nofollow: boolean; text: string | null; url: string }[]
    nofollow: number
    total: number
  } | null
  looksClientRendered: boolean
  meta: PageMeta | null
  structuredData: StructuredDataBlock[] | null
  tags: PageTag[] | null
  wordCount: number
}

export type InspectedSitemap = {
  entries: { lastmod: string | null; loc: string }[]
  index: boolean
  total: number
}

export type InspectedRobots = {
  groups: { allow: string[]; crawlDelay: number | null; disallow: string[]; userAgents: string[] }[]
  sitemaps: string[]
}

export type InspectPageResult = {
  blockedBySite: boolean
  fetchedAt: string
  finalUrl: string
  kind: InspectedKind | null
  note: string | null
  page: InspectedPage | null
  redirects: WebRedirect[]
  robots: InspectedRobots | null
  sitemap: InspectedSitemap | null
  status: number
}

export function inspectPageArgsUrl(value: unknown): string | null {
  if (!isRecord(value)) return null
  return safeHttpUrl(nodeText(value["url"]))
}

// Server strings arrive as untrusted nodes; links stay http(s) only, and malformed list items drop.
export function inspectPageResult(value: unknown): InspectPageResult | null {
  if (!isRecord(value) || !Array.isArray(value["redirects"])) return null
  const finalUrl = safeHttpUrl(nodeText(value["final_url"]))
  const { fetched_at: fetchedAt, kind, status } = value
  if (
    finalUrl === null ||
    !isNonNegativeInteger(status) ||
    typeof fetchedAt !== "string" ||
    (kind !== null && !isOneOf(KINDS, kind))
  ) {
    return null
  }
  const redirects = webRedirects(value["redirects"])
  if (redirects === null) return null
  return {
    blockedBySite: value["blocked_by_site"] === true,
    fetchedAt,
    finalUrl,
    kind,
    note: typeof value["note"] === "string" ? value["note"] : null,
    page: kind === "page" ? inspectedPage(value["page"]) : null,
    redirects,
    robots: kind === "robots" ? inspectedRobots(value["robots"]) : null,
    sitemap: kind === "sitemap" ? inspectedSitemap(value["sitemap"]) : null,
    status,
  }
}

function inspectedPage(value: unknown): InspectedPage | null {
  if (!isRecord(value) || !isNonNegativeInteger(value["word_count"])) return null
  const { headings, images, links, meta } = value
  const data = value["structured_data"]
  return {
    headings: isRecord(headings)
      ? {
          h1Count: count(headings["h1_count"]),
          items: records(headings["items"]).flatMap((item) =>
            isNonNegativeInteger(item["level"])
              ? [{ level: item["level"], text: nodeText(item["text"]) }]
              : []
          ),
        }
      : null,
    images: isRecord(images)
      ? {
          items: records(images["items"]).map((item) => ({
            alt: nodeText(item["alt"]),
            src: nodeText(item["src"]),
          })),
          missingAlt: count(images["missing_alt"]),
          total: count(images["total"]),
        }
      : null,
    links: isRecord(links)
      ? {
          external: count(links["external"]),
          internal: count(links["internal"]),
          items: records(links["items"]).flatMap((item) => {
            const url = safeHttpUrl(nodeText(item["url"]))
            return url
              ? [
                  {
                    internal: item["internal"] === true,
                    nofollow: item["nofollow"] === true,
                    text: nodeText(item["text"]),
                    url,
                  },
                ]
              : []
          }),
          nofollow: count(links["nofollow"]),
          total: count(links["total"]),
        }
      : null,
    looksClientRendered: value["looks_client_rendered"] === true,
    meta: isRecord(meta) ? pageMeta(meta) : null,
    structuredData: isRecord(data)
      ? records(data["blocks"]).flatMap((block) => {
          const content = nodeText(block["content"])
          return content === null
            ? []
            : [
                {
                  content,
                  truncated: block["truncated"] === true,
                  types: texts(block["types"]),
                  valid: block["valid"] === true,
                },
              ]
        })
      : null,
    tags: Array.isArray(value["tags"]) ? records(value["tags"]).flatMap(pageTag) : null,
    wordCount: value["word_count"],
  }
}

function pageMeta(meta: Record<string, unknown>): PageMeta {
  return {
    canonical: nodeText(meta["canonical"]),
    description: nodeText(meta["description"]),
    language: nodeText(meta["language"]),
    metaRefresh: nodeText(meta["meta_refresh"]),
    robots: nodeText(meta["robots"]),
    title: nodeText(meta["title"]),
    viewport: nodeText(meta["viewport"]),
  }
}

function pageTag(value: Record<string, unknown>): PageTag[] {
  const { category, found_in: foundIn, id, vendor } = value
  return typeof vendor === "string" &&
    typeof category === "string" &&
    typeof foundIn === "string" &&
    (id === null || typeof id === "string")
    ? [{ category, foundIn, id, vendor }]
    : []
}

function inspectedSitemap(value: unknown): InspectedSitemap | null {
  if (!isRecord(value) || !isNonNegativeInteger(value["total"])) return null
  return {
    entries: records(value["entries"]).flatMap((entry) => {
      const loc = nodeText(entry["loc"])
      const lastmod = typeof entry["lastmod"] === "string" ? entry["lastmod"] : null
      return loc ? [{ lastmod, loc }] : []
    }),
    index: value["type"] === "sitemapindex",
    total: value["total"],
  }
}

function inspectedRobots(value: unknown): InspectedRobots | null {
  if (!isRecord(value)) return null
  return {
    groups: records(value["groups"]).map((group) => ({
      allow: texts(group["allow"]),
      crawlDelay: typeof group["crawl_delay"] === "number" ? group["crawl_delay"] : null,
      disallow: texts(group["disallow"]),
      userAgents: texts(group["user_agents"]),
    })),
    sitemaps: texts(value["sitemaps"]),
  }
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.flatMap((item) => nodeText(item) ?? []) : []
}

function count(value: unknown): number {
  return isNonNegativeInteger(value) ? value : 0
}
