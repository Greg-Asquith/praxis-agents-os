// apps/web/src/features/conversations/components/tools/web/web-redirects.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type WebRedirect = { location: string; status: number }

// Returns null when any hop is malformed, so a tampered result doesn't render a partial chain.
export function webRedirects(value: unknown[]): WebRedirect[] | null {
  const redirects: WebRedirect[] = []
  for (const hop of value) {
    const location = isRecord(hop) ? nodeText(hop["location"]) : null
    if (!isRecord(hop) || location === null || !isNonNegativeInteger(hop["status"])) return null
    redirects.push({ location, status: hop["status"] })
  }
  return redirects
}
