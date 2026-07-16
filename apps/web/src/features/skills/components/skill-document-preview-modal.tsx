// apps/web/src/features/skills/components/skill-document-preview-modal.tsx

import { useQuery } from "@tanstack/react-query"
import { DownloadIcon, FileTextIcon, LoaderCircleIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { skillDocumentMarkdownQueryOptions } from "@/features/skills/api/get-skill-document-markdown"
import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import type { SkillDocument } from "@/features/skills/types"
import { getErrorMessage } from "@/lib/api/errors"

export function SkillDocumentPreviewModal({
  document,
  onClose,
  onDownload,
  skillId,
}: {
  document: SkillDocument | null
  onClose: () => void
  onDownload: (document: SkillDocument) => void
  skillId: string
}) {
  if (!document) {
    return null
  }

  return (
    <SkillDocumentPreviewDialog
      document={document}
      onClose={onClose}
      onDownload={onDownload}
      skillId={skillId}
    />
  )
}

function SkillDocumentPreviewDialog({
  document,
  onClose,
  onDownload,
  skillId,
}: {
  document: SkillDocument
  onClose: () => void
  onDownload: (document: SkillDocument) => void
  skillId: string
}) {
  const markdownQuery = useQuery(skillDocumentMarkdownQueryOptions(skillId, document.name))

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose()
        }
      }}
    >
      <DialogContent className="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b p-5 pr-12">
          <div className="flex min-w-0 items-start gap-3">
            <div className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg border">
              <FileTextIcon className="size-4" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="truncate">{document.name}</DialogTitle>
              <DialogDescription className="mt-1 truncate">
                {document.filename} · Rendered from the converted document
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto p-5">
          {markdownQuery.isPending ? (
            <div className="text-muted-foreground flex min-h-56 items-center justify-center gap-2 text-sm">
              <LoaderCircleIcon className="size-4 animate-spin" />
              Preparing preview
            </div>
          ) : markdownQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Preview unavailable</AlertTitle>
              <AlertDescription>{getErrorMessage(markdownQuery.error)}</AlertDescription>
            </Alert>
          ) : (
            <div className="flex flex-col gap-4">
              {markdownQuery.data.truncated ? (
                <Alert>
                  <AlertTitle>Preview shortened</AlertTitle>
                  <AlertDescription>
                    This document is too large to show in full. Download it to read everything.
                  </AlertDescription>
                </Alert>
              ) : null}
              <article className="min-w-0">
                <MessageMarkdown content={markdownQuery.data.content} />
              </article>
            </div>
          )}
        </div>

        <DialogFooter className="mx-0 mb-0 rounded-none px-5 py-4" showCloseButton>
          <Button
            onClick={() => {
              onDownload(document)
            }}
            type="button"
            variant="outline"
          >
            <DownloadIcon data-icon="inline-start" />
            Download
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
