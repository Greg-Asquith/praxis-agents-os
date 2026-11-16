// apps/web/src/integrations/provider-file-viewer.tsx

import { useCallback, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2Icon } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  providerFileViewQueryOptions,
  type ProviderFileSource,
  type SaveToFilesMutation,
  type ViewableKind,
} from "@/integrations/file-sources"
import { SaveToFiles } from "@/integrations/save-to-files-button"
import { getErrorMessage } from "@/lib/api/errors"

/** Shows a provider image, video, or audio file from bytes fetched for this view only. */
export function ProviderFileViewer({
  conversationId,
  kind,
  onOpenChange,
  open,
  save,
  source,
}: {
  conversationId: string
  kind: Exclude<ViewableKind, "pdf">
  onOpenChange: (open: boolean) => void
  open: boolean
  save: SaveToFilesMutation
  source: ProviderFileSource
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] min-w-0 overflow-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="wrap-break-word">{source.name}</DialogTitle>
        </DialogHeader>
        {open ? <ViewerBody conversationId={conversationId} kind={kind} source={source} /> : null}
        <DialogFooter>
          <SaveToFiles save={save} source={source} />
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ViewerBody({
  conversationId,
  kind,
  source,
}: {
  conversationId: string
  kind: Exclude<ViewableKind, "pdf">
  source: ProviderFileSource
}) {
  const query = useQuery(providerFileViewQueryOptions(conversationId, source))
  if (query.isPending) {
    return (
      <div className="text-muted-foreground flex min-h-48 items-center justify-center gap-2 text-sm">
        <Loader2Icon className="size-4 animate-spin motion-reduce:animate-none" />
        Loading {source.name}
      </div>
    )
  }
  if (query.isError) {
    return (
      <p className="text-destructive text-sm" role="alert">
        {getErrorMessage(query.error)}
      </p>
    )
  }
  return <BlobMedia blob={query.data} kind={kind} name={source.name} />
}

function BlobMedia({
  blob,
  kind,
  name,
}: {
  blob: Blob
  kind: Exclude<ViewableKind, "pdf">
  name: string
}) {
  const [failed, setFailed] = useState(false)
  // The object URL lives only while the element is mounted.
  const mediaRef = useCallback(
    (element: HTMLImageElement | HTMLMediaElement | null) => {
      if (!element) return
      const url = URL.createObjectURL(blob)
      element.src = url
      return () => {
        URL.revokeObjectURL(url)
      }
    },
    [blob]
  )
  const onError = () => {
    setFailed(true)
  }
  if (failed) {
    return (
      <p className="text-destructive text-sm" role="alert">
        This file could not be shown. Save it to Files to open it.
      </p>
    )
  }
  if (kind === "image") {
    return (
      <div className="bg-muted/40 flex items-center justify-center overflow-hidden rounded-lg border p-3">
        <img
          alt={name}
          className="max-h-[70dvh] max-w-full object-contain"
          onError={onError}
          ref={mediaRef}
        />
      </div>
    )
  }
  if (kind === "video") {
    return (
      <video
        aria-label={name}
        className="bg-media max-h-[70dvh] w-full rounded-lg border"
        controls
        onError={onError}
        playsInline
        ref={mediaRef}
      >
        <track kind="captions" />
      </video>
    )
  }
  return (
    <audio aria-label={`Play ${name}`} className="w-full" controls onError={onError} ref={mediaRef}>
      <track kind="captions" />
    </audio>
  )
}
