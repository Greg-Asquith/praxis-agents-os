// apps/web/src/features/conversations/components/fetch-url-result.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { type WebRedirect, webRedirects } from "@/features/conversations/components/web-redirects"
import { isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export const FETCH_URL_TOOL_NAME = "fetch_url"

type FetchUrlFormat = "markdown" | "text" | "html" | "unsupported"

const FORMATS: ReadonlySet<FetchUrlFormat> = new Set(["markdown", "text", "html", "unsupported"])

type SavedReference = { id: string; label: string }

export type FetchUrlResult = {
  blockedBySite: boolean
  content: string | null
  contentType: string
  fetchedAt: string
  file: SavedReference | null
  finalUrl: string
  format: FetchUrlFormat
  knowledgeBaseDocument: SavedReference | null
  note: string | null
  redirects: WebRedirect[]
  requestedUrl: string
  status: number
  title: string | null
  truncated: boolean
}

export function fetchUrlArgsUrl(value: unknown): string | null {
  if (!isRecord(value)) return null
  return safeHttpUrl(nodeText(value["url"]))
}

// Server strings arrive as untrusted nodes; links stay http(s) only.
export function fetchUrlResult(value: unknown): FetchUrlResult | null {
  if (!isRecord(value) || !Array.isArray(value["redirects"])) return null
  const requestedUrl = safeHttpUrl(nodeText(value["requested_url"]))
  const finalUrl = safeHttpUrl(nodeText(value["final_url"]))
  const status = value["status"]
  const format = value["format"]
  const fetchedAt = value["fetched_at"]
  const contentType = nodeText(value["content_type"])
  if (
    requestedUrl === null ||
    finalUrl === null ||
    !isNonNegativeInteger(status) ||
    !isOneOf(FORMATS, format) ||
    typeof fetchedAt !== "string" ||
    contentType === null
  ) {
    return null
  }
  const redirects = webRedirects(value["redirects"])
  if (redirects === null) return null
  return {
    blockedBySite: value["blocked_by_site"] === true,
    content: nodeText(value["content"]),
    contentType,
    fetchedAt,
    file: savedReference(value["file"]),
    finalUrl,
    format,
    knowledgeBaseDocument: savedReference(value["knowledge_base_document"]),
    note: typeof value["note"] === "string" ? value["note"] : null,
    redirects,
    requestedUrl,
    status,
    title: nodeText(value["title"]),
    truncated: value["truncated"] === true,
  }
}

function savedReference(value: unknown): SavedReference | null {
  if (!isRecord(value)) return null
  const id = value["entity_id"]
  const label = value["label"]
  return typeof id === "string" && typeof label === "string" ? { id, label } : null
}
