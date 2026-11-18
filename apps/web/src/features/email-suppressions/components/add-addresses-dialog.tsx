// apps/web/src/features/email-suppressions/components/add-addresses-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { PlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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
import { Textarea } from "@/components/ui/textarea"
import { useAddEmailSuppressionsMutation } from "@/features/email-suppressions/api/add-email-suppressions"
import { parsePastedAddresses } from "@/features/email-suppressions/parse-addresses"
import type { EmailSuppressionAddResponse } from "@/features/email-suppressions/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

const MAX_ADDRESSES = 1_000
const PREVIEW_LIMIT = 30

export function AddAddressesDialog({
  onAdded,
}: {
  onAdded: (result: EmailSuppressionAddResponse) => void
}) {
  const mutation = useAddEmailSuppressionsMutation()
  const [open, setOpen] = useState(false)
  const [pasted, setPasted] = useState("")
  const [error, setError] = useState<string | null>(null)
  const addresses = parsePastedAddresses(pasted)
  const tooMany = addresses.length > MAX_ADDRESSES

  function handleOpenChange(next: boolean) {
    if (mutation.isPending) return
    setOpen(next)
    if (!next) {
      setPasted("")
      setError(null)
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const reason = formString(new FormData(event.currentTarget), "reason").trim()
    mutation.mutate(
      { addresses, reason },
      {
        onSuccess: (result) => {
          onAdded(result)
          handleOpenChange(false)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button />}>
        <PlusIcon data-icon="inline-start" />
        Add Addresses
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add to Do Not Email</DialogTitle>
          <DialogDescription>
            Agents in this workspace can&apos;t email anyone you add, from any mailbox.
          </DialogDescription>
        </DialogHeader>
        <form id="add-email-suppressions-form" onSubmit={handleSubmit}>
          <FieldGroup>
            {error ? (
              <Alert variant="destructive">
                <AlertTitle>Addresses not added</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <Field>
              <FieldLabel htmlFor="email-suppression-addresses">Email Addresses</FieldLabel>
              <Textarea
                className="max-h-48 min-h-24"
                id="email-suppression-addresses"
                onChange={(event) => {
                  setPasted(event.target.value)
                }}
                placeholder="dana@example.com, kai@example.com"
                value={pasted}
              />
              <FieldDescription>
                Paste one or many, separated by commas or new lines. Each address also covers
                versions with a tag, such as dana+news@example.com.
              </FieldDescription>
            </Field>
            {addresses.length > 0 ? <PastePreview addresses={addresses} /> : null}
            {tooMany ? (
              <Alert variant="destructive">
                <AlertDescription>
                  Add up to {MAX_ADDRESSES.toLocaleString()} addresses at a time.
                </AlertDescription>
              </Alert>
            ) : null}
            <Field>
              <FieldLabel htmlFor="email-suppression-reason">Reason</FieldLabel>
              <Input
                id="email-suppression-reason"
                maxLength={500}
                name="reason"
                placeholder="Asked not to be contacted"
                required
              />
              <FieldDescription>Saved with each address. Agents never see it.</FieldDescription>
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button
            disabled={mutation.isPending}
            onClick={() => {
              handleOpenChange(false)
            }}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button
            disabled={addresses.length === 0 || tooMany || mutation.isPending}
            form="add-email-suppressions-form"
            type="submit"
          >
            {mutation.isPending ? "Adding" : addLabel(addresses.length)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PastePreview({ addresses }: { addresses: string[] }) {
  const hidden = addresses.length - PREVIEW_LIMIT
  return (
    <div aria-live="polite" className="flex flex-col gap-2">
      <p className="text-muted-foreground text-xs">
        Read {addresses.length.toLocaleString()} {addresses.length === 1 ? "address" : "addresses"}
      </p>
      <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto">
        {addresses.slice(0, PREVIEW_LIMIT).map((address) => (
          <Badge key={address} variant="outline">
            {address}
          </Badge>
        ))}
        {hidden > 0 ? <Badge variant="secondary">{hidden.toLocaleString()} more</Badge> : null}
      </div>
    </div>
  )
}

function addLabel(count: number) {
  if (count === 0) return "Add Addresses"
  return `Add ${count.toLocaleString()} ${count === 1 ? "Address" : "Addresses"}`
}
