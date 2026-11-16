// apps/web/src/integrations/save-to-files-button.tsx

import { CheckIcon, FolderDownIcon, Loader2Icon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  type ProviderFileSource,
  useActionableConversation,
  useSaveToFiles,
} from "@/integrations/file-sources"
import { getErrorMessage } from "@/lib/api/errors"

/** Saves one provider file on click, then links it in Files; hidden on read-only views. */
export function SaveToFiles(props: ProviderFileSource) {
  const conversationId = useActionableConversation()
  if (conversationId === null) return null
  return <SaveToFilesAction conversationId={conversationId} {...props} />
}

function SaveToFilesAction({
  conversationId,
  name,
  providerKey,
  reference,
}: ProviderFileSource & { conversationId: string }) {
  const save = useSaveToFiles(conversationId)
  const saved = save.data
  if (saved) {
    return (
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <CheckIcon className="text-success size-3.5" />
        Saved.
        <a
          className="text-link hover:text-primary underline underline-offset-2"
          href={saved.fileHref}
        >
          Open in Files
        </a>
      </p>
    )
  }
  return (
    <div className="grid justify-items-end gap-1">
      <Button
        aria-label={`Save ${name} to Files`}
        disabled={save.isPending}
        onClick={() => {
          save.mutate({ name, providerKey, reference })
        }}
        size="xs"
        type="button"
        variant="outline"
      >
        {save.isPending ? (
          <Loader2Icon className="animate-spin motion-reduce:animate-none" />
        ) : (
          <FolderDownIcon />
        )}
        {save.isPending ? "Saving…" : "Save to Files"}
      </Button>
      {save.isError ? (
        <p className="text-destructive text-right text-xs" role="alert">
          {getErrorMessage(save.error)}
        </p>
      ) : null}
    </div>
  )
}
