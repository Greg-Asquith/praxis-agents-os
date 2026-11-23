// apps/web/src/features/conversations/api/save-fetched-page.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { parseSavedFile } from "@/components/tool-ui/saved-file"
import { apiRequest } from "@/lib/api/client"
import { baseFilesQueryKeys } from "@/lib/file-query-keys"

/** Fetches the page again and saves it into Files as the signed-in person; no agent turn. */
export function useSaveFetchedPage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ conversationId, url }: { conversationId: string; url: string }) => {
      const saved = parseSavedFile(
        await apiRequest<unknown>("/web/page-saves", {
          method: "POST",
          body: { conversation_id: conversationId, url },
        })
      )
      if (!saved) throw new Error("The page was saved, but its details couldn't be shown.")
      return saved
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: baseFilesQueryKeys.lists() }),
  })
}
