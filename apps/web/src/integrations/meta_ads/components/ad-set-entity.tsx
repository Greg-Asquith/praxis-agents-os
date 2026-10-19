// apps/web/src/integrations/meta_ads/components/ad-set-entity.tsx

import { useInfiniteQuery } from "@tanstack/react-query"
import { use } from "react"

import {
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { FormField } from "@/integrations/meta_ads/components/campaign-controls"
import type { EntityReferenceValue } from "@/features/tools/types"
import { getErrorMessage } from "@/lib/api/errors"

const CURRENT = "current"

/** Picks the Page, pixel, or app a goal needs from what the ad account can use.
 *
 * Inside a structured field, `fieldKey` is that field and `entityKind` names the kind. */
export function EntityPicker({
  currentLabel,
  disabled,
  entityKind,
  fieldKey,
  label,
  onChoose,
  toolName = "meta_ads_create_ad_set",
}: {
  currentLabel: string | null
  disabled: boolean
  entityKind?: string
  fieldKey: string
  label: string
  onChoose: (value: EntityReferenceValue) => void
  toolName?: string
}) {
  const conversationId = use(ToolConversationContext)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      entityKind,
      fieldKey,
      pageSize: 25,
      search: "",
      toolName,
    }),
    enabled: conversationId !== null,
  })
  const choices = mergeEntityChoices([], results.data?.pages ?? [])
  const options = [
    ...(currentLabel ? [{ key: CURRENT, label: currentLabel }] : []),
    ...choices
      .filter((choice) => choice.label !== currentLabel)
      .map((choice) => ({ key: choice.identity.join("/"), label: choice.label })),
  ]
  return (
    <FormField label={label}>
      {(id) => (
        <>
          <Select<string>
            disabled={disabled || conversationId === null}
            onValueChange={(key) => {
              const chosen = choices.find((choice) => choice.identity.join("/") === key)
              if (chosen) onChoose(chosen.value)
            }}
            value={currentLabel ? CURRENT : null}
          >
            <SelectTrigger className="w-full" id={id}>
              <SelectValue placeholder={results.isPending ? "Loading" : `Choose a ${label}`} />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                {options.map((option) => (
                  <SelectItem key={option.key} label={option.label} value={option.key}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          {results.isError ? (
            <p className="text-destructive text-sm">{getErrorMessage(results.error)}</p>
          ) : null}
        </>
      )}
    </FormField>
  )
}
