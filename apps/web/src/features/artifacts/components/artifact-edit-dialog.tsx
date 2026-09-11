// apps/web/src/features/artifacts/components/artifact-edit-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { PencilIcon } from "lucide-react"

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import { platformArtifactQueryKeys } from "@/features/artifacts/api/platform-list-artifacts"
import { useUpdatePlatformArtifactMutation } from "@/features/artifacts/api/platform-update-artifact"
import { useUpdateArtifactMutation } from "@/features/artifacts/api/update-artifact"
import { describeArtifactSaveError, isStaleArtifactError } from "@/features/artifacts/format"
import type { Artifact } from "@/features/artifacts/types"
import { formString } from "@/lib/forms"

function saveDescription(artifact: Artifact) {
  if (artifact.scope !== "platform") {
    return "Saving creates a new version. Earlier versions stay intact."
  }
  return artifact.is_published
    ? "Saving creates a new version that becomes visible to every workspace immediately."
    : "Saving creates a new version. It stays unavailable to other workspaces until you publish it."
}

export function ArtifactEditDialog({
  artifact,
  content,
  defaultOpen = false,
  onSaved,
}: {
  artifact: Artifact
  content: string
  defaultOpen?: boolean
  onSaved: (artifact: Artifact) => void
}) {
  const queryClient = useQueryClient()
  const workspaceMutation = useUpdateArtifactMutation()
  const platformMutation = useUpdatePlatformArtifactMutation()
  const [open, setOpen] = useState(defaultOpen)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const isPlatform = artifact.scope === "platform"
  const pending = workspaceMutation.isPending || platformMutation.isPending

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const input = { content: formString(form, "content"), title: formString(form, "title") }
    setError(null)
    setStale(false)
    try {
      const saved = isPlatform
        ? await platformMutation.mutateAsync({
            ...input,
            artifactId: artifact.id,
            expectedCurrentVersionId: artifact.current_version_id,
          })
        : await workspaceMutation.mutateAsync({ ...input, artifactId: artifact.id })
      onSaved(saved)
      setOpen(false)
    } catch (submitError) {
      setStale(isStaleArtifactError(submitError))
      setError(describeArtifactSaveError(submitError))
    }
  }

  // Reloading refreshes the reviewed version while the uncontrolled fields keep the typed text.
  async function reloadLatest() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: artifactQueryKeys.detail(artifact.id) }),
      queryClient.invalidateQueries({ queryKey: platformArtifactQueryKeys.detail(artifact.id) }),
    ])
    setError(null)
    setStale(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" />}>
        <PencilIcon data-icon="inline-start" />
        Edit
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <form className="grid gap-4" onSubmit={(event) => void handleSubmit(event)}>
          <DialogHeader>
            <DialogTitle>{isPlatform ? "Edit Shared Artifact" : "Edit Artifact"}</DialogTitle>
            <DialogDescription>{saveDescription(artifact)}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="artifact-title">Title</Label>
            <Input defaultValue={artifact.title} id="artifact-title" name="title" required />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="artifact-content">Content</Label>
            <Textarea
              className="min-h-72 font-mono text-xs"
              defaultValue={content}
              id="artifact-content"
              name="content"
              required
            />
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>
                {stale ? "This artifact changed while you were editing" : "Couldn’t save"}
              </AlertTitle>
              <AlertDescription>
                {stale
                  ? "Someone saved a newer version. Reload it to review the latest content before saving again. Your unsaved text stays in this editor."
                  : error}
              </AlertDescription>
              {stale ? (
                <AlertAction>
                  <Button
                    onClick={() => void reloadLatest()}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Reload
                  </Button>
                </AlertAction>
              ) : null}
            </Alert>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button disabled={pending} type="submit">
              {pending
                ? "Saving…"
                : isPlatform && artifact.is_published
                  ? "Save for Every Workspace"
                  : "Save New Version"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
