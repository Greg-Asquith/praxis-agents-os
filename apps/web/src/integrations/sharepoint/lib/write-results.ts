// apps/web/src/integrations/sharepoint/lib/write-results.ts

import { fanOutEntries } from "@/components/tool-ui/fan-out"
import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { sharePointItem } from "@/integrations/sharepoint/lib/items"
import { isNullableString, isOneOf, isRecord } from "@/lib/guards"

type WriteOutcome = "applied" | "failed" | "unverified"
export type SharePointWriteResult = {
  outcome: WriteOutcome
  detail: string | null
  errorCode: string | null
  item: { name: string; path: string; sizeBytes: number; webUrl: string | null } | null
}

const OUTCOMES: ReadonlySet<WriteOutcome> = new Set(["applied", "failed", "unverified"])
const RECOVERY: Record<string, string> = {
  version_conflict: "The file changed in SharePoint. Read it again before replacing it.",
  name_exists: "A file with this name exists. Replace it or choose another name.",
  locked: "The item is locked. Try again after the lock is released.",
  quota_exceeded:
    "The library has no storage space left. Free space in SharePoint before trying again.",
  upload_session_expired:
    "The upload session expired. Check the library before preparing a new upload.",
  invalid_range:
    "The upload range was rejected. Check the file in SharePoint before preparing a new upload.",
  unsupported_type:
    "Choose a supported File type and a valid destination. Text content needs a text file.",
  too_large: "The file exceeds the upload limit. Use a smaller file.",
  source_changed:
    "The workspace File changed after review. Ask the agent to prepare it for approval again.",
  source_unavailable: "The workspace File is unavailable. Choose another File or upload it again.",
  type_mismatch: "Match the source File type to the new filename or the file being replaced.",
  empty_content: "Choose a File with content before saving.",
  unverified_mutation:
    "The change could not be confirmed. Check the library in SharePoint before trying again.",
}

export function sharePointWriteRecovery(code: string | null, fallback: string): string {
  return code && Object.hasOwn(RECOVERY, code) ? (RECOVERY[code] ?? fallback) : fallback
}

function writeResultHeader(value: unknown) {
  if (!isRecord(value) || !isOneOf(OUTCOMES, value["outcome"])) return null
  const detail = value["detail"] ?? null
  const errorCode = value["error_code"] ?? null
  if (!isNullableString(detail) || !isNullableString(errorCode)) return null
  return { outcome: value["outcome"], detail, errorCode }
}

export function sharePointWriteResult(value: unknown): SharePointWriteResult | null {
  const header = writeResultHeader(value)
  if (!header || !isRecord(value)) return null
  if (value["item"] == null) {
    return header.outcome === "applied" ? null : { ...header, item: null }
  }
  const item = sharePointItem(value["item"])
  if (!item) return null
  return {
    ...header,
    item: {
      name: item.name,
      path: item.path,
      sizeBytes: item.sizeBytes,
      webUrl: safeHttpUrl(item.webUrl),
    },
  }
}

// Keep malformed writes on the default row; valid errors use provider recovery copy.
export function sharePointWriteEnvelope(value: unknown) {
  const entries = fanOutEntries(value)
  if (
    !entries ||
    entries.some(
      (entry) =>
        (entry.status === "success" || entry.data != null) && !sharePointWriteResult(entry.data)
    )
  )
    return null
  return {
    results: entries.map((entry) => ({
      provider_key: entry.providerKey,
      display_name: entry.displayName,
      external_id: entry.externalId,
      status: entry.status,
      data: entry.data,
      error_code: entry.errorCode,
      error_message: sharePointWriteRecovery(
        entry.errorCode ?? null,
        entry.errorMessage ?? "The change could not be completed."
      ),
    })),
  }
}
