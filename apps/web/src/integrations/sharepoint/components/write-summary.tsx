// apps/web/src/integrations/sharepoint/components/write-summary.tsx

import { use } from "react"
import { useQuery } from "@tanstack/react-query"

import { DetailList } from "@/components/tool-ui/detail-list"
import { entityReferenceHydrationQueryOptions } from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import type { SharePointWriteArgs } from "@/integrations/sharepoint/lib/write-args"
import type { EntityChoice } from "@/features/tools/types"

export function SharePointWriteSummary({
  args,
  tool,
}: {
  args: SharePointWriteArgs
  tool: string
}) {
  const { choice, pending } = useDestinationLookup(args, tool)
  return <DetailList items={destinationDetails(args, choice, pending)} />
}

function useDestinationLookup(args: SharePointWriteArgs, tool: string) {
  const conversationId = use(ToolConversationContext)
  const lookup = useQuery({
    ...entityReferenceHydrationQueryOptions({
      conversationId: conversationId ?? "",
      toolName: tool,
      fieldKey: args.fieldKey,
      dependentArgs: {},
      exactValues: args.destination ? [args.destination.value] : [],
    }),
    enabled: Boolean(conversationId && args.destination),
  })
  return {
    choice: lookup.data?.choices[0],
    pending: Boolean(conversationId && lookup.isPending),
  }
}

function destinationDetails(
  args: SharePointWriteArgs,
  choice: EntityChoice | undefined,
  pending: boolean
) {
  const items = [
    { label: "Library", value: choice?.scope_label ?? args.library },
    {
      label: args.name === null ? "File to replace" : "Destination",
      value: choice?.label ?? (args.destination ? args.destination.label : "Library root"),
    },
  ]
  if (args.destination)
    items.push({ label: "Location", value: destinationLocation(choice, pending) })
  return items
}

function destinationLocation(choice: EntityChoice | undefined, pending: boolean): string {
  const path = choice?.description?.split("\n").slice(1).join("\n")
  if (path) return path
  return pending
    ? "Looking up the path…"
    : "Path unavailable. Check the destination in SharePoint before approving."
}
