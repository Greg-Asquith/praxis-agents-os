// apps/web/src/features/knowledge/components/copy-document-button.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { CopyIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog"
import { useCopyDocumentMutation } from "@/features/knowledge/api/copy-document"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import { knowledgeContentText } from "@/features/knowledge/content"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { getErrorMessage } from "@/lib/api/errors"

export function CopyDocumentButton({ document }: { document: KbDocumentDetail }) {
  const mutation = useCopyDocumentMutation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [isPrivate, setIsPrivate] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const content = knowledgeContentText(document.content_md)
  async function copyDocument() {
    if (!content) return
    setError(null)
    try {
      const copy = await mutation.mutateAsync({
        title: document.title,
        contentMd: content,
        isPrivate,
      })
      setOpen(false)
      await navigate({
        to: "/knowledge/$documentId",
        params: { documentId: copy.id },
        search: {},
      })
    } catch (cause) {
      setError(getErrorMessage(cause))
    }
  }

  return (
    <>
      <Button
        disabled={!content}
        variant="outline"
        onClick={() => {
          setIsPrivate(true)
          setError(null)
          setOpen(true)
        }}
      >
        <CopyIcon data-icon="inline-start" />
        Make a workspace copy
      </Button>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!mutation.isPending) setOpen(nextOpen)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Make a workspace copy?</DialogTitle>
            <DialogDescription>
              Your copy is independent and receives no future updates to the shared document.
            </DialogDescription>
          </DialogHeader>
          <PrivacyField
            checked={isPrivate}
            onCheckedChange={setIsPrivate}
            sharedDescription="Everyone in this workspace can search and read your copy."
          />
          {error ? (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button disabled={mutation.isPending} variant="outline" />}>
              Cancel
            </DialogClose>
            <Button disabled={mutation.isPending} onClick={() => void copyDocument()}>
              {mutation.isPending ? "Copying…" : "Make a workspace copy"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
