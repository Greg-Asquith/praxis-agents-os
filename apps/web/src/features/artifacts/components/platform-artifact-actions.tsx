// apps/web/src/features/artifacts/components/platform-artifact-actions.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { GlobeIcon, Trash2Icon, UndoIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useDeletePlatformArtifactMutation } from "@/features/artifacts/api/platform-delete-artifact"
import { usePublishPlatformArtifactMutation } from "@/features/artifacts/api/platform-publish-artifact"
import { useWithdrawPlatformArtifactMutation } from "@/features/artifacts/api/platform-withdraw-artifact"
import { PLATFORM_AUDIENCE_STATEMENT } from "@/features/artifacts/components/publish-artifact-dialog"
import { describeArtifactSaveError } from "@/features/artifacts/format"
import type { Artifact } from "@/features/artifacts/types"

type Action = "publish" | "withdraw" | "delete"

const ACTION_COPY: Record<
  Action,
  { label: string; title: string; description: (currentVersionNumber: number) => string }
> = {
  publish: {
    label: "Publish",
    title: "Publish to every workspace?",
    description: (currentVersionNumber) =>
      `Version ${String(currentVersionNumber)} becomes available in every workspace on this deployment.`,
  },
  withdraw: {
    label: "Withdraw",
    title: "Withdraw from every workspace?",
    description: () =>
      "This artifact becomes unavailable in every workspace. Existing copies and content already used in chats remain.",
  },
  delete: {
    label: "Delete",
    title: "Delete this shared artifact?",
    description: () =>
      "This artifact is removed from every workspace. Independent copies and content already used in chats remain.",
  },
}

export function PlatformArtifactActions({
  artifact,
  currentVersionNumber,
}: {
  artifact: Artifact
  currentVersionNumber: number
}) {
  const publish = usePublishPlatformArtifactMutation()
  const withdraw = useWithdrawPlatformArtifactMutation()
  const remove = useDeletePlatformArtifactMutation()
  const navigate = useNavigate()
  const [action, setAction] = useState<Action | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = publish.isPending || withdraw.isPending || remove.isPending

  function start(next: Action) {
    setError(null)
    setAction(next)
  }

  async function confirm() {
    setError(null)
    try {
      if (action === "publish") {
        await publish.mutateAsync({
          artifactId: artifact.id,
          expectedCurrentVersionId: artifact.current_version_id,
        })
      } else if (action === "withdraw") {
        await withdraw.mutateAsync(artifact.id)
        // Withdrawn artifacts leave tenant reads, so stay on the management view.
        await navigate({
          to: "/artifacts/$artifactId",
          params: { artifactId: artifact.id },
          search: { platform: true },
          replace: true,
        })
      } else if (action === "delete") {
        await remove.mutateAsync(artifact.id)
        await navigate({ to: "/artifacts", search: { scope: "platform" } })
      }
      setAction(null)
    } catch (cause) {
      setError(describeArtifactSaveError(cause))
    }
  }

  const copy = action ? ACTION_COPY[action] : null
  return (
    <>
      {artifact.is_published ? (
        <Button
          disabled={pending}
          onClick={() => {
            start("withdraw")
          }}
          type="button"
          variant="outline"
        >
          <UndoIcon data-icon="inline-start" />
          Withdraw
        </Button>
      ) : (
        <Button
          disabled={pending}
          onClick={() => {
            start("publish")
          }}
          type="button"
        >
          <GlobeIcon data-icon="inline-start" />
          Publish
        </Button>
      )}
      <Button
        disabled={pending}
        onClick={() => {
          start("delete")
        }}
        type="button"
        variant="destructive"
      >
        <Trash2Icon data-icon="inline-start" />
        Delete
      </Button>
      <ConfirmDialog
        confirmLabel={copy?.label ?? "Confirm"}
        confirmPendingLabel="Saving…"
        description={
          <>
            {copy?.description(currentVersionNumber) ?? PLATFORM_AUDIENCE_STATEMENT}
            {error ? (
              <span className="text-destructive mt-2 block" role="alert">
                {error}
              </span>
            ) : null}
          </>
        }
        isPending={pending}
        onConfirm={confirm}
        onOpenChange={(open) => {
          if (!open) setAction(null)
        }}
        open={action !== null}
        title={copy?.title ?? "Review shared artifact"}
        variant={action === "publish" ? "default" : "destructive"}
      />
    </>
  )
}
