// apps/web/src/features/artifacts/components/artifact-edit-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { PencilIcon } from "lucide-react"

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
import { useUpdateArtifactMutation } from "@/features/artifacts/api/update-artifact"
import type { Artifact } from "@/features/artifacts/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function ArtifactEditDialog({
  artifactId,
  content,
  onUpdated,
  title,
}: {
  artifactId: string
  content: string
  onUpdated: (artifact: Artifact) => void
  title: string
}) {
  const mutation = useUpdateArtifactMutation()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError(null)
    try {
      const artifact = await mutation.mutateAsync({
        artifactId,
        content: formString(form, "content"),
        title: formString(form, "title"),
      })
      onUpdated(artifact)
      setOpen(false)
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <PencilIcon data-icon="inline-start" />
        Edit
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <form className="grid gap-4" onSubmit={(event) => void handleSubmit(event)}>
          <DialogHeader>
            <DialogTitle>Edit Artifact</DialogTitle>
            <DialogDescription>
              Saving creates a new version. Earlier versions stay intact.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="artifact-title">Title</Label>
            <Input defaultValue={title} id="artifact-title" name="title" required />
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
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button disabled={mutation.isPending} type="submit">
              {mutation.isPending ? "Saving…" : "Save New Version"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
