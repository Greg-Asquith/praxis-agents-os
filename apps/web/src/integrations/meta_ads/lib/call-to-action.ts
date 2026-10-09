// apps/web/src/integrations/meta_ads/lib/call-to-action.ts

import { isRecord, isStringArray } from "@/lib/guards"

export const DEFAULT_BUTTON = "LEARN_MORE"

export type ButtonLists = { website: string[]; app: string[] }

export function parseButtonLists(value: unknown): ButtonLists | null {
  if (!isRecord(value) || !isStringArray(value["website"]) || !isStringArray(value["app"]))
    return null
  return { website: value["website"], app: value["app"] }
}

/** Lists the buttons every given goal accepts; Meta's dry run is the final check. */
export function allowedButtons(
  lists: ButtonLists,
  objectives: readonly (string | null)[]
): string[] {
  const [first, ...rest] = objectives.map((objective) =>
    objective === "OUTCOME_APP_PROMOTION" ? lists.app : lists.website
  )
  return (first ?? lists.website).filter((button) => rest.every((list) => list.includes(button)))
}
