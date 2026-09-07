// apps/web/src/components/tool-ui/keyvalue-field-values.ts

import type { EditedKeyValue } from "@/components/tool-ui/edited-values"

export function nextKeyValueFieldName(value: EditedKeyValue, lockedEntries: string[]): string {
  let index = Object.keys(value).length + 1
  let key = `field${String(index)}`
  while (Object.hasOwn(value, key) || lockedEntries.includes(key)) {
    index += 1
    key = `field${String(index)}`
  }
  return key
}
