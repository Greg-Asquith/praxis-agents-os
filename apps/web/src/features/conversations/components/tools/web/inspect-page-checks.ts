// apps/web/src/features/conversations/components/tools/web/inspect-page-checks.ts

import type { InspectedPage } from "@/features/conversations/components/tools/web/inspect-page-result"
import { pluralize } from "@/lib/format"

type PageCheckTone = "warning" | "pass" | "info"

export type PageCheck = { label: string; tone: PageCheckTone }

// Search results show about this many characters before cutting a title or description.
const TITLE_MAX_CHARS = 60
const DESCRIPTION_MAX_CHARS = 160
const TONE_ORDER: Record<PageCheckTone, number> = { warning: 0, pass: 1, info: 2 }

// Plain-language findings for the facts the agent asked for, problems first.
export function pageChecks(page: InspectedPage, finalUrl: string): PageCheck[] {
  const checks: PageCheck[] = []
  if (page.looksClientRendered) {
    checks.push(warning("Built by scripts in the browser, so the source may miss content"))
  }
  const { headings, images, links, meta, tags } = page
  if (meta) {
    checks.push(lengthCheck("Title", meta.title, TITLE_MAX_CHARS))
    checks.push(lengthCheck("Description", meta.description, DESCRIPTION_MAX_CHARS))
    if (meta.canonical === null) checks.push(warning("No canonical URL"))
    else if (comparableUrl(meta.canonical) === comparableUrl(finalUrl)) {
      checks.push(pass("Canonical points to this page"))
    } else checks.push(info("Canonical points to another URL"))
    if (/\b(noindex|none)\b/i.test(meta.robots ?? "")) {
      checks.push(warning("Marked noindex, so search engines won't list it"))
    } else {
      checks.push(pass("Search engines can index it"))
    }
    if (!meta.language) checks.push(warning("No page language set"))
    if (!meta.viewport) checks.push(warning("No mobile viewport set"))
    if (meta.metaRefresh) checks.push(warning("Uses a meta refresh"))
  }
  if (headings) {
    const count = headings.h1Count
    if (count === 1) checks.push(pass("One H1 heading"))
    else checks.push(warning(count === 0 ? "No H1 heading" : `${String(count)} H1 headings`))
  }
  if (images) {
    const { missingAlt, total } = images
    if (total === 0) checks.push(info("No images"))
    else if (missingAlt === 0) checks.push(pass(`All ${countOf(total, "image")} have alt text`))
    else
      checks.push(warning(`${String(missingAlt)} of ${countOf(total, "image")} missing alt text`))
  }
  if (links) {
    const nofollow = links.nofollow > 0 ? `, ${String(links.nofollow)} nofollow` : ""
    checks.push(
      info(
        `${countOf(links.total, "link")}: ${String(links.internal)} internal, ${String(links.external)} external${nofollow}`
      )
    )
  }
  if (page.structuredData && page.structuredData.length > 0) {
    const broken = page.structuredData.filter((block) => !block.valid).length
    if (broken > 0) {
      checks.push(warning(`${countOf(broken, "structured data block")} doesn't parse`))
    }
    const types = [...new Set(page.structuredData.flatMap((block) => block.types))]
    checks.push(info(`Structured data: ${types.join(", ") || "no types"}`))
  }
  if (tags) {
    const vendors = [...new Set(tags.map((tag) => tag.vendor))]
    checks.push(info(vendors.length > 0 ? vendors.join(", ") : "No tracking tags found"))
  }
  checks.push(info(countOf(page.wordCount, "word")))
  return checks.sort((a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone])
}

function lengthCheck(label: string, value: string | null, max: number): PageCheck {
  if (!value) return warning(`No ${label.toLowerCase()}`)
  const length = countOf(value.length, "character")
  return value.length > max
    ? warning(`${label} is ${length}; search results show about ${String(max)}`)
    : pass(`${label} is ${length}`)
}

// Paths are case-sensitive; the URL parser lower-cases the scheme and host only.
function comparableUrl(value: string): string {
  try {
    const url = new URL(value)
    url.hash = ""
    return url.href.replace(/\/+$/, "")
  } catch {
    return value
  }
}

function countOf(count: number, noun: string): string {
  return `${count.toLocaleString("en-GB")} ${pluralize(count, noun)}`
}

const warning = (label: string): PageCheck => ({ label, tone: "warning" })
const pass = (label: string): PageCheck => ({ label, tone: "pass" })
const info = (label: string): PageCheck => ({ label, tone: "info" })
