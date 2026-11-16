// apps/web/src/integrations/provider-file-row.tsx

import { EyeIcon, Loader2Icon, PaperclipIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  type ProviderFileSource,
  type SaveToFilesMutation,
  useSaveToFiles,
  useViewProviderFile,
} from "@/integrations/file-sources"
import { ProviderFileViewer } from "@/integrations/provider-file-viewer"
import { SaveToFiles } from "@/integrations/save-to-files-button"
import { formatBytes } from "@/lib/format"

type ProviderFileProps = { contentType: string | null; source: ProviderFileSource }
type ViewerProps = {
  save: SaveToFilesMutation
  source: ProviderFileSource
  viewer: ReturnType<typeof useViewProviderFile>
}

/** One provider file whose name opens it, with View and Save to Files actions. */
export function ProviderFileRow({
  contentType,
  sizeBytes,
  source,
}: ProviderFileProps & { sizeBytes: number | null }) {
  const viewer = useViewProviderFile(source, contentType)
  const save = useSaveToFiles()
  return (
    <li className="grid min-w-0 gap-1.5 rounded-md border px-2.5 py-2">
      <div className="flex min-w-0 items-center gap-2.5">
        <PaperclipIcon className="text-muted-foreground size-3.5 shrink-0" />
        <div className="min-w-0 flex-1">
          {viewer.view ? (
            <button
              className="hover:text-primary block max-w-full cursor-pointer truncate text-left text-sm underline-offset-2 hover:underline"
              onClick={viewer.view}
              title={`View ${source.name}`}
              type="button"
            >
              {source.name}
            </button>
          ) : (
            <p className="truncate text-sm" title={source.name}>
              {source.name}
            </p>
          )}
          {sizeBytes !== null ? (
            <p className="text-muted-foreground text-xs">{formatBytes(sizeBytes)}</p>
          ) : null}
        </div>
        <ViewerActions save={save} source={source} viewer={viewer} />
      </div>
      <ViewerStatus save={save} source={source} viewer={viewer} />
    </li>
  )
}

/** View and Save to Files actions for a card that already names the file. */
export function ProviderFileActions({ contentType, source }: ProviderFileProps) {
  const viewer = useViewProviderFile(source, contentType)
  const save = useSaveToFiles()
  return (
    <div className="grid min-w-0 justify-items-end gap-1.5">
      <ViewerActions save={save} source={source} viewer={viewer} />
      <ViewerStatus save={save} source={source} viewer={viewer} />
    </div>
  )
}

function ViewerActions({ save, source, viewer }: ViewerProps) {
  return (
    <div className="flex shrink-0 items-start gap-1.5">
      {viewer.view ? (
        <Button
          aria-label={`View ${source.name}`}
          disabled={viewer.opening}
          onClick={viewer.view}
          size="xs"
          type="button"
          variant="outline"
        >
          {viewer.opening ? (
            <Loader2Icon className="animate-spin motion-reduce:animate-none" />
          ) : (
            <EyeIcon />
          )}
          View
        </Button>
      ) : null}
      <SaveToFiles save={save} source={source} />
    </div>
  )
}

function ViewerStatus({ save, source, viewer }: ViewerProps) {
  return (
    <>
      {viewer.error ? (
        <p className="text-destructive text-xs" role="alert">
          {viewer.error}
        </p>
      ) : null}
      {viewer.conversationId !== null && viewer.kind !== null && viewer.kind !== "pdf" ? (
        <ProviderFileViewer
          conversationId={viewer.conversationId}
          kind={viewer.kind}
          onOpenChange={viewer.setDialogOpen}
          open={viewer.dialogOpen}
          save={save}
          source={source}
        />
      ) : null}
    </>
  )
}
