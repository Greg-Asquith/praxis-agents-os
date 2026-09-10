// apps/web/src/features/conversations/components/conversation-sharing-dialog.tsx

import { Share2Icon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useUpdateSharing } from "@/features/conversations/api/update-sharing"
import type { ConversationDetail } from "@/features/conversations/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { getErrorMessage } from "@/lib/api/errors"

export function ConversationSharingDialog({ conversation }: { conversation: ConversationDetail }) {
  const { workspace } = useActiveWorkspace()
  const mutation = useUpdateSharing(conversation.id)
  const { copy, copied } = useClipboardCopy()
  if (
    workspace.is_personal ||
    (!conversation.capabilities?.can_manage_sharing && !conversation.capabilities?.can_stop_sharing)
  )
    return null
  const shared = conversation.visibility === "workspace"
  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Share2Icon data-icon="inline-start" />
        Share
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share chat with {workspace.name}</DialogTitle>
          <DialogDescription>
            Everyone in this workspace can read this chat, including future messages. Results may
            include information from your personal connections. Sharing does not give others access
            to those connections.
          </DialogDescription>
        </DialogHeader>
        {shared ? (
          <p className="text-muted-foreground text-sm">
            Stopping sharing blocks future chat reads. Copied text, downloaded files, and workspace
            file access remain available.
          </p>
        ) : null}
        {mutation.error ? (
          <p role="alert" className="text-destructive text-sm">
            {getErrorMessage(mutation.error)}
          </p>
        ) : null}
        <DialogFooter>
          {shared && conversation.capabilities.can_stop_sharing ? (
            <Button
              variant="outline"
              disabled={mutation.isPending}
              onClick={() => {
                mutation.mutate("private")
              }}
            >
              Stop sharing
            </Button>
          ) : null}
          {shared ? (
            <Button
              onClick={() =>
                void copy(
                  `${window.location.origin}/shared-chats/${workspace.id}/${conversation.id}`
                )
              }
            >
              {copied ? "Link copied" : "Copy link"}
            </Button>
          ) : null}
          {!shared && conversation.capabilities.can_manage_sharing ? (
            <Button
              disabled={mutation.isPending}
              onClick={() => {
                mutation.mutate("workspace")
              }}
            >
              Share with workspace
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
