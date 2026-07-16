// apps/web/src/features/workspaces/components/create-invitation-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { CheckIcon, CopyIcon, MailPlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCreateInvitationMutation } from "@/features/workspaces/api/create-invitation"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import type { WorkspaceRole } from "@/features/workspaces/types"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { getErrorMessage } from "@/lib/api/errors"
import { formNumber, formString } from "@/lib/forms"

const ROLE_OPTIONS: { label: string; value: WorkspaceRole }[] = [
  { label: "Admin", value: "admin" },
  { label: "Member", value: "member" },
  { label: "Read Only", value: "read_only" },
]

function invitationLink(token: string) {
  return `${window.location.origin}/invitations/accept?token=${encodeURIComponent(token)}`
}

export function CreateInvitationDialog() {
  const { workspace } = useActiveWorkspace()
  const createInvitationMutation = useCreateInvitationMutation()
  const copyCode = useClipboardCopy()
  const copyLink = useClipboardCopy()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [role, setRole] = useState<WorkspaceRole>("member")

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setError(null)
      setToken(null)
      setRole("member")
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setToken(null)

    const formData = new FormData(event.currentTarget)

    createInvitationMutation.mutate(
      {
        workspaceId: workspace.id,
        payload: {
          email: formString(formData, "email"),
          expires_in_days: formNumber(formData, "expires_in_days", 7),
          role,
        },
      },
      {
        onSuccess: (response) => {
          setToken(response.token)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button variant="outline" />}>
        <MailPlusIcon data-icon="inline-start" />
        Invite
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite member</DialogTitle>
          <DialogDescription>
            Send access to {workspace.name}. Choose the role before creating the invite.
          </DialogDescription>
        </DialogHeader>
        <form id="create-invitation-form" onSubmit={handleSubmit}>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Invitation not created</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {token && (
              <Alert>
                <AlertTitle>Invitation created</AlertTitle>
                <AlertDescription>
                  Share this token with the invitee if email delivery is not configured.
                </AlertDescription>
              </Alert>
            )}
            {token && (
              <Field>
                <FieldLabel htmlFor="invitation-token">Token</FieldLabel>
                <Input id="invitation-token" readOnly value={token} />
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => {
                      void copyCode.copy(token)
                    }}
                  >
                    {copyCode.copied ? (
                      <CheckIcon data-icon="inline-start" />
                    ) : (
                      <CopyIcon data-icon="inline-start" />
                    )}
                    {copyCode.copied ? "Copied Code" : "Copy Code"}
                  </Button>
                  <Button
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => {
                      void copyLink.copy(invitationLink(token))
                    }}
                  >
                    {copyLink.copied ? (
                      <CheckIcon data-icon="inline-start" />
                    ) : (
                      <CopyIcon data-icon="inline-start" />
                    )}
                    {copyLink.copied ? "Copied Link" : "Copy Link"}
                  </Button>
                </div>
              </Field>
            )}
            <Field>
              <FieldLabel htmlFor="invitation-email">Email</FieldLabel>
              <Input
                id="invitation-email"
                name="email"
                placeholder="teammate@example.com"
                required
                type="email"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="invitation-role">Role</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setRole(value === "admin" || value === "read_only" ? value : "member")
                }}
                value={role}
              >
                <SelectTrigger id="invitation-role" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    {ROLE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="invitation-days">Expires in days</FieldLabel>
              <Input
                defaultValue={7}
                id="invitation-days"
                max={30}
                min={1}
                name="expires_in_days"
                required
                type="number"
              />
              <FieldDescription>Choose between 1 and 30 days.</FieldDescription>
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            onClick={() => {
              handleOpenChange(false)
            }}
          >
            Close
          </Button>
          <Button
            disabled={createInvitationMutation.isPending}
            form="create-invitation-form"
            type="submit"
          >
            {createInvitationMutation.isPending ? "Creating" : "Create Invite"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
