// apps/web/src/components/tool-ui/untrusted-node.ts

import { isRecord } from "@/lib/guards"

export type UntrustedNode = {
  node: "praxis_untrusted"
  source_kind: string
  source_ref: string
  content: string
}

export function isUntrustedNode(value: unknown): value is UntrustedNode {
  return (
    isRecord(value) &&
    value["node"] === "praxis_untrusted" &&
    typeof value["source_kind"] === "string" &&
    typeof value["source_ref"] === "string" &&
    typeof value["content"] === "string"
  )
}

export function nodeText(value: unknown): string | null {
  if (typeof value === "string") {
    return value
  }
  return isUntrustedNode(value) ? value.content : null
}
