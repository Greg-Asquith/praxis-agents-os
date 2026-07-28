// apps/web/src/features/artifacts/components/artifact-share-dialog.tsx

import { useState } from "react"
import { CheckIcon, CopyIcon, LinkIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCreateArtifactShareMutation } from "@/features/artifacts/api/create-artifact-share"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { getErrorMessage } from "@/lib/api/errors"

export function ArtifactShareDialog({
  artifactId,
  currentVersionNumber,
}: {
  artifactId: string
  currentVersionNumber: number
}) {
  const mutation = useCreateArtifactShareMutation()
  const { copied, copy } = useClipboardCopy()
  const [open, setOpen] = useState(false)
  const [expiresInDays, setExpiresInDays] = useState(7)
  const [shareUrl, setShareUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) {
      setShareUrl(null)
      setError(null)
    }
  }

  async function handleCreate() {
    setError(null)
    try {
      const created = await mutation.mutateAsync({ artifactId, expiresInDays })
      setShareUrl(created.share_url)
    } catch (createError) {
      setError(getErrorMessage(createError))
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button size="sm" />}>
        <LinkIcon data-icon="inline-start" />
        Share
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share Artifact</DialogTitle>
          <DialogDescription>
            The link opens current version {String(currentVersionNumber)} directly and stops working
            when it expires or is revoked.
          </DialogDescription>
        </DialogHeader>
        {shareUrl ? (
          <div className="grid gap-3">
            <div className="grid gap-2">
              <Label htmlFor="artifact-share-url">Share Link</Label>
              <div className="flex gap-2">
                <input
                  className="border-input bg-muted/30 min-w-0 flex-1 rounded-lg border px-3 text-sm"
                  id="artifact-share-url"
                  readOnly
                  value={shareUrl}
                />
                <Button onClick={() => void copy(shareUrl)} type="button" variant="outline">
                  {copied ? (
                    <CheckIcon data-icon="inline-start" />
                  ) : (
                    <CopyIcon data-icon="inline-start" />
                  )}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
            <p className="text-muted-foreground text-xs">
              Copy this link now. For security, Praxis will not show the full link again.
            </p>
          </div>
        ) : (
          <div className="grid gap-2">
            <Label>Link Expires After</Label>
            <Select
              value={expiresInDays}
              onValueChange={(value) => {
                if (value) setExpiresInDays(value)
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={1}>1 day</SelectItem>
                <SelectItem value={7}>7 days</SelectItem>
                <SelectItem value={30}>30 days</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        {error ? <p className="text-destructive text-sm">{error}</p> : null}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            {shareUrl ? "Done" : "Cancel"}
          </DialogClose>
          {!shareUrl ? (
            <Button disabled={mutation.isPending} onClick={() => void handleCreate()} type="button">
              {mutation.isPending ? "Creating…" : "Create Share Link"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
