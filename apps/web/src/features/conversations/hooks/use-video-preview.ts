// apps/web/src/features/conversations/hooks/use-video-preview.ts

import { useQuery } from "@tanstack/react-query"

import { filePreviewQueryOptions } from "@/features/files/api/preview-file"

// A refetch swaps the signed URL and restarts playback, so keep the first one.
export function useVideoPreview(fileId: string) {
  return useQuery({
    ...filePreviewQueryOptions(fileId),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })
}
