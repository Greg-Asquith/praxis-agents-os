// apps/web/src/integrations/file-sources.ts

import { use, useState } from "react"
import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query"

import {
  SharedTranscriptContext,
  ToolConversationContext,
} from "@/components/tool-ui/tool-conversation-context"
import { workspaceMediaKind } from "@/components/tool-ui/workspace-file-preview"
import { parseSavedFile } from "@/integrations/saved-file"
import { apiFetch, apiRequest } from "@/lib/api/client"
import { getErrorMessage, parseApiError } from "@/lib/api/errors"
import { baseFilesQueryKeys } from "@/lib/file-query-keys"
import { baseIntegrationQueryKeys } from "@/lib/integration-query-keys"
import { openSignedResource } from "@/lib/open-signed-resource"

// The new tab has loaded the PDF long before this; the URL only needs to outlive navigation.
const PDF_URL_LIFETIME_MS = 60_000

export type ProviderFileSource = {
  name: string
  providerKey: string
  reference: Record<string, unknown>
}

export type ViewableKind = "image" | "video" | "audio" | "pdf"

// Matches the route's viewable types; other documents open once saved to Files.
function viewableKind(contentType: string | null): ViewableKind | null {
  if (contentType === null) return null
  if (contentType.split(";")[0]?.trim().toLowerCase() === "application/pdf") return "pdf"
  return workspaceMediaKind(contentType)
}

/** Fetches a provider file's bytes for this view only; nothing is saved. */
async function fetchProviderFile(
  conversationId: string,
  source: ProviderFileSource,
  signal?: AbortSignal
): Promise<Blob> {
  const response = await apiFetch(`/integrations/conversations/${conversationId}/file-views`, {
    body: { provider_key: source.providerKey, reference: source.reference },
    cache: "no-store",
    method: "POST",
    ...(signal ? { signal } : {}),
  })
  if (!response.ok) throw await parseApiError(response)
  return response.blob()
}

// Bytes are held only while the viewer is open.
export function providerFileViewQueryOptions(conversationId: string, source: ProviderFileSource) {
  return queryOptions({
    queryKey: [
      ...baseIntegrationQueryKeys.workspace(),
      "conversation",
      conversationId,
      "file-view",
      source,
    ],
    queryFn: ({ signal }) => fetchProviderFile(conversationId, source, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
}

/** The conversation a card can act in, or null on shared transcripts and outside chats. */
export function useActionableConversation(): string | null {
  const conversationId = use(ToolConversationContext)
  const shared = use(SharedTranscriptContext)
  return shared ? null : conversationId
}

/** Opens media in a dialog and PDFs in a new tab; `view` is null when the file can't be shown. */
export function useViewProviderFile(source: ProviderFileSource, contentType: string | null) {
  const conversationId = useActionableConversation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const kind = viewableKind(contentType)

  async function openPdf(id: string) {
    setError(null)
    setOpening(true)
    try {
      await openSignedResource(async () => {
        const url = URL.createObjectURL(await fetchProviderFile(id, source))
        window.setTimeout(() => {
          URL.revokeObjectURL(url)
        }, PDF_URL_LIFETIME_MS)
        return url
      })
    } catch (openError) {
      setError(getErrorMessage(openError))
    } finally {
      setOpening(false)
    }
  }

  const view =
    conversationId === null || kind === null
      ? null
      : kind === "pdf"
        ? () => {
            void openPdf(conversationId)
          }
        : () => {
            setDialogOpen(true)
          }
  return { conversationId, dialogOpen, error, kind, opening, setDialogOpen, view }
}

/** Saves a provider file into Files as the signed-in person; no agent turn is involved. */
export function useSaveToFiles() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      conversationId,
      source,
    }: {
      conversationId: string
      source: ProviderFileSource
    }) => {
      const saved = parseSavedFile(
        await apiRequest<unknown>(`/integrations/conversations/${conversationId}/file-saves`, {
          method: "POST",
          body: { provider_key: source.providerKey, reference: source.reference },
        })
      )
      if (!saved) throw new Error("The file was saved, but its details couldn't be shown.")
      return saved
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: baseFilesQueryKeys.lists() }),
  })
}

export type SaveToFilesMutation = ReturnType<typeof useSaveToFiles>
