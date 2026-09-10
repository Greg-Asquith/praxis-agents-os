// apps/web/src/features/knowledge/components/platform-document-actions.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"

import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { usePlatformPublishDocumentMutation } from "@/features/knowledge/api/platform-publish-document"
import { usePlatformWithdrawDocumentMutation } from "@/features/knowledge/api/platform-withdraw-document"
import { usePlatformReprocessDocumentMutation } from "@/features/knowledge/api/platform-reprocess-document"
import { usePlatformDeleteDocumentMutation } from "@/features/knowledge/api/platform-delete-document"
import { ManualDocumentForm } from "@/features/knowledge/components/manual-document-form"
import { knowledgeContentText } from "@/features/knowledge/content"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { getErrorMessage } from "@/lib/api/errors"

type Action = "publish" | "withdraw" | "delete"
const ACTION_COPY = {
  publish: {
    label: "Publish",
    title: "Publish to every workspace?",
    description:
      "Everyone on this platform can search and read this document. Review its content before publishing.",
  },
  withdraw: {
    label: "Withdraw",
    title: "Withdraw from every workspace?",
    description:
      "This document becomes unavailable for search and reading. Existing copies and content already used in chats remain.",
  },
  delete: {
    label: "Delete",
    title: "Delete this shared document?",
    description:
      "This document is removed from every workspace. Independent copies and content already used in chats remain.",
  },
}

export function PlatformDocumentActions({ document }: { document: KbDocumentDetail }) {
  const publish = usePlatformPublishDocumentMutation()
  const withdraw = usePlatformWithdrawDocumentMutation()
  const reprocess = usePlatformReprocessDocumentMutation()
  const remove = usePlatformDeleteDocumentMutation()
  const navigate = useNavigate()
  const [action, setAction] = useState<Action | null>(null)
  const [reviewedVersion, setReviewedVersion] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pending = publish.isPending || withdraw.isPending || reprocess.isPending || remove.isPending
  const processing = document.status === "pending" || document.status === "processing"
  const version = document.meta["ingestion_version"]
  const canPublish =
    document.status === "ready" &&
    typeof version === "string" &&
    Boolean(knowledgeContentText(document.content_md))

  async function run(actionFn: () => Promise<unknown>) {
    setError(null)
    try {
      await actionFn()
      setAction(null)
    } catch (cause) {
      setError(getErrorMessage(cause))
    }
  }

  async function confirm() {
    if (action === "publish" && reviewedVersion !== null) {
      await run(() =>
        publish.mutateAsync({ documentId: document.id, expectedIngestionVersion: reviewedVersion })
      )
    } else if (action === "withdraw") {
      await run(() => withdraw.mutateAsync(document.id))
    } else if (action === "delete") {
      await run(async () => {
        await remove.mutateAsync(document.id)
        await navigate({ to: "/knowledge", search: { scope: "platform" } })
      })
    }
  }

  const copy = action ? ACTION_COPY[action] : null
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap justify-end gap-2">
        {document.is_published || processing ? (
          <Button
            disabled={pending}
            variant="outline"
            onClick={() => {
              setError(null)
              setAction("withdraw")
            }}
          >
            Withdraw
          </Button>
        ) : (
          <>
            {document.source_type === "manual" ? (
              <Button
                disabled={pending || processing}
                variant="outline"
                onClick={() => {
                  setEditing(true)
                }}
              >
                Edit
              </Button>
            ) : null}
            <Button
              disabled={pending || processing}
              variant="outline"
              onClick={() => void run(() => reprocess.mutateAsync(document.id))}
            >
              Reprocess
            </Button>
            <Button
              disabled={pending || !canPublish}
              onClick={() => {
                setError(null)
                setReviewedVersion(typeof version === "string" ? version : null)
                setAction("publish")
              }}
            >
              Publish
            </Button>
          </>
        )}
        <Button
          disabled={pending}
          variant="destructive"
          onClick={() => {
            setError(null)
            setAction("delete")
          }}
        >
          Delete
        </Button>
      </div>
      {error && !action ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit shared knowledge</DialogTitle>
            <DialogDescription>
              Save and review the processed content before publishing it again.
            </DialogDescription>
          </DialogHeader>
          <ManualDocumentForm
            document={document}
            platform
            onSaved={() => {
              setEditing(false)
            }}
          />
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open) setAction(null)
        }}
        title={copy?.title ?? "Review shared knowledge"}
        description={
          <>
            {copy?.description}
            {error ? (
              <span role="alert" className="text-destructive mt-2 block">
                {error}
              </span>
            ) : null}
          </>
        }
        confirmLabel={copy?.label ?? "Confirm"}
        confirmPendingLabel="Saving…"
        isPending={pending}
        variant={action === "publish" ? "default" : "destructive"}
        onConfirm={confirm}
      />
    </div>
  )
}
