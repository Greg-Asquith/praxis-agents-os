// apps/web/src/integrations/meta_ads/lib/meta-pictures.ts

import { useQuery } from "@tanstack/react-query"
import { createContext, use } from "react"

import { providerPreviewQueryOptions } from "@/components/tool-ui/provider-preview-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"

// The ad account whose pictures the card shows, as the conversation's context names it.
export const MediaAccountContext = createContext<string | null>(null)

const JPEG_DATA_URL = /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/

/** Reads a picture Meta holds for this ad account, by preview ref such as image_HASH or page_ID. */
export function useMetaPicture(ref: string | null): { loading: boolean; src: string | null } {
  const conversationId = use(ToolConversationContext)
  const accountId = use(MediaAccountContext)
  const query = useQuery({
    ...providerPreviewQueryOptions({
      conversationId,
      providerKey: "meta_ads",
      kind: "meta_ads_media",
      scopeId: accountId ?? "",
      ref: ref ?? "",
    }),
    enabled: conversationId !== null && accountId !== null && ref !== null,
  })
  const content = query.data?.content_type === "image" ? query.data.content : null
  return {
    loading: query.isLoading,
    src: content && JPEG_DATA_URL.test(content) ? content : null,
  }
}
