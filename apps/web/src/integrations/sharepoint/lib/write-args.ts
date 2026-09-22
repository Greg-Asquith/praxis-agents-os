// apps/web/src/integrations/sharepoint/lib/write-args.ts

import { isOneOf, isRecord, optionalString, stringValue } from "@/lib/guards"
import {
  sharePointFileSource,
  sharePointSourceDetails,
  type SharePointFileSource,
  type SharePointSourceDetails,
} from "@/integrations/sharepoint/lib/file-source"

type ItemReference = {
  driveId: string
  label: string
  kind: "file" | "folder" | null
  value: Record<string, unknown>
}

export type SharePointWriteArgs = {
  fieldKey: "parent" | "folder" | "file"
  library: string
  name: string | null
  destination: ItemReference | null
  content: string | null
  source: SharePointFileSource | null
  sourceDetails: SharePointSourceDetails | null
}

const ITEM_KINDS = new Set(["file", "folder"] as const)

function itemIdentity(value: unknown) {
  if (!isRecord(value) || value["entity_kind"] !== "sharepoint_drive_item") return null
  const driveId = stringValue(value["drive_id"])
  const itemId = stringValue(value["item_id"])
  return driveId && itemId ? { value, driveId } : null
}

function itemReference(value: unknown): ItemReference | null {
  const identity = itemIdentity(value)
  if (!identity) return null
  const kind = identity.value["kind"] ?? null
  if (kind !== null && !isOneOf(ITEM_KINDS, kind)) return null
  return {
    ...identity,
    label: stringValue(identity.value["label"]) ?? "SharePoint item",
    kind,
  }
}

function requiredWriteFields(
  value: Record<string, unknown>,
  field: SharePointWriteArgs["fieldKey"]
) {
  if (field === "file") return stringValue(value["expected_version"]) ? { name: null } : null
  const name = optionalString(value["name"])
  if (name === null) return null
  return { name }
}

function destinationLibrary(value: Record<string, unknown>, destination: ItemReference | null) {
  const target = value["_target"]
  if (destination && (!isRecord(target) || destination.driveId !== target["drive_id"]))
    return "Library containing the selected item"
  return optionalString(value["_library"]) ?? "Selected library"
}

function writeArgs(
  value: unknown,
  field: SharePointWriteArgs["fieldKey"]
): SharePointWriteArgs | null {
  if (!isRecord(value)) return null
  const destination = itemReference(value[field])
  if (value[field] != null && !destination) return null
  if (field === "file" && !destination) return null
  const fields = requiredWriteFields(value, field)
  if (!fields) return null
  const source = sharePointFileSource(value["source"])
  if (value["source"] != null && !source) return null
  if (value["content"] != null && typeof value["content"] !== "string") return null
  return {
    fieldKey: field,
    library: destinationLibrary(value, destination),
    destination,
    content: field === "parent" ? null : optionalString(value["content"]),
    source,
    sourceDetails: sharePointSourceDetails(value["_source"]),
    ...fields,
  }
}

export const sharePointCreateFolderArgs = (value: unknown) => writeArgs(value, "parent")
export const sharePointWriteFileArgs = (value: unknown) => writeArgs(value, "folder")
export const sharePointUpdateFileArgs = (value: unknown) => writeArgs(value, "file")

function nameError(name: string): string | null {
  if (!name || Array.from(name).length > 255) return "Enter a name between 1 and 255 characters."
  if (/\p{Surrogate}/u.test(name)) return "Enter a valid Unicode name."
  if (/^[ .]|[ .]$|^~\$/.test(name))
    return "Use a name without leading or trailing spaces or dots, or a ~$ prefix."
  if (/[/\\:*?"<>|]/.test(name) || /\p{Cc}/u.test(name))
    return "The name contains a character SharePoint does not allow."
  if (/^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)|^desktop\.ini$|_vti_/iu.test(name)) {
    return "SharePoint reserves this name. Choose another name."
  }
  return null
}

function destinationError(args: SharePointWriteArgs): string | null {
  if (args.name !== null) {
    const error = nameError(args.name)
    if (error) return error
    if (args.destination?.kind === "file") return "Choose a folder as the destination."
  } else if (args.destination?.kind === "folder") return "Choose a file to replace."
  return null
}

function contentError(content: string | null): string | null {
  if (content === null) return null
  if (!content.length) return "Enter content before saving the file."
  if (/\p{Surrogate}/u.test(content)) return "Enter valid Unicode text."
  for (const char of content) {
    if (/\p{Cc}/u.test(char) && char !== "\n" && char !== "\t")
      return "Text cannot contain control characters other than newline and tab."
  }
  return null
}

export function validateSharePointWriteArgs(args: SharePointWriteArgs | null): string | null {
  if (!args) return "Review the name, destination, and content before approving."
  const error = destinationError(args) ?? contentError(args.content)
  if (error || args.fieldKey === "parent") return error
  if (args.content !== null && args.source)
    return "Choose either text content or a workspace File, not both."
  if (args.content === null && !args.source) return "Enter text content or choose a workspace File."
  if (args.source && args.source.id !== args.sourceDetails?.id)
    return "Review the selected File before approving."
  return null
}
