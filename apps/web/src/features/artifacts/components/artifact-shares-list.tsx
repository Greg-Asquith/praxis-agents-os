// apps/web/src/features/artifacts/components/artifact-shares-list.tsx

import { useState } from "react"
import { BanIcon, LinkIcon } from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useArtifactSharesQuery } from "@/features/artifacts/api/list-artifact-shares"
import { useRevokeArtifactShareMutation } from "@/features/artifacts/api/revoke-artifact-share"
import { formatDateTime } from "@/lib/format"
import { getErrorMessage } from "@/lib/api/errors"

export function ArtifactSharesList({ artifactId }: { artifactId: string }) {
  const { data } = useArtifactSharesQuery(artifactId)
  const mutation = useRevokeArtifactShareMutation()
  const [shareToRevoke, setShareToRevoke] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleRevoke() {
    if (!shareToRevoke) return
    setError(null)
    try {
      await mutation.mutateAsync({ artifactId, shareId: shareToRevoke })
      setShareToRevoke(null)
    } catch (revokeError) {
      setError(getErrorMessage(revokeError))
    }
  }

  if (data.items.length === 0) {
    return (
      <div className="bg-muted/30 flex items-center gap-3 rounded-lg border border-dashed p-4">
        <LinkIcon className="text-muted-foreground size-4" />
        <p className="text-muted-foreground text-sm">No active or recently revoked links.</p>
      </div>
    )
  }

  return (
    <div className="grid gap-2">
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <ConfirmDialog
        confirmIcon={<BanIcon data-icon="inline-start" />}
        confirmLabel="Revoke Link"
        confirmPendingLabel="Revoking"
        description="Anyone using this link will immediately see a not found page."
        isPending={mutation.isPending}
        onConfirm={handleRevoke}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setShareToRevoke(null)
          }
        }}
        open={shareToRevoke !== null}
        title="Revoke this share link?"
      />
      {data.items.map((share) => (
        <div
          className="border-border flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center"
          key={share.id}
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <code className="text-sm">{share.token_prefix}…</code>
              <Badge variant={share.revoked_at ? "secondary" : "success"}>
                {share.revoked_at ? "Revoked" : "Active"}
              </Badge>
            </div>
            <p className="text-muted-foreground mt-1 text-xs">
              Expires {formatDateTime(share.expires_at)} · {String(share.access_count)} opens
              {share.creator_display ? ` · Created by ${share.creator_display}` : ""}
            </p>
          </div>
          {!share.revoked_at ? (
            <Button
              onClick={() => {
                setShareToRevoke(share.id)
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              Revoke
            </Button>
          ) : null}
        </div>
      ))}
    </div>
  )
}
