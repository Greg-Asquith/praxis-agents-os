// apps/web/src/features/email-suppressions/components/do-not-email-panel.tsx

import { useState } from "react"
import { MailXIcon, Trash2Icon } from "lucide-react"

import { DebouncedSearchInput } from "@/components/forms/debounced-search-input"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { useEmailSuppressionsQuery } from "@/features/email-suppressions/api/list-email-suppressions"
import { useRemoveEmailSuppressionMutation } from "@/features/email-suppressions/api/remove-email-suppression"
import { AddAddressesDialog } from "@/features/email-suppressions/components/add-addresses-dialog"
import { EmailSuppressionsTable } from "@/features/email-suppressions/components/email-suppressions-table"
import type {
  EmailSuppression,
  EmailSuppressionAddResponse,
} from "@/features/email-suppressions/types"
import { getErrorMessage } from "@/lib/api/errors"

const PAGE_SIZE = 25

export function DoNotEmailPanel({ canRemove }: { canRemove: boolean }) {
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [addResult, setAddResult] = useState<EmailSuppressionAddResponse | null>(null)
  const [removeTarget, setRemoveTarget] = useState<EmailSuppression | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)
  const query = useEmailSuppressionsQuery({ limit: PAGE_SIZE, offset, search })
  const removeMutation = useRemoveEmailSuppressionMutation()
  const data = query.data

  async function removeEntry() {
    if (!removeTarget) return
    setRemoveError(null)
    try {
      await removeMutation.mutateAsync(removeTarget.id)
      setRemoveTarget(null)
    } catch (error) {
      setRemoveError(getErrorMessage(error))
      setRemoveTarget(null)
    }
  }

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader className="px-1">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Do Not Email</CardTitle>
            <CardDescription className="mt-1 max-w-2xl">
              People on this list are never emailed from this workspace, whichever mailbox or agent
              sends. Agents can&apos;t see the list or the reasons.
            </CardDescription>
          </div>
          <AddAddressesDialog onAdded={setAddResult} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-1">
        {addResult ? <AddResultAlert result={addResult} /> : null}
        {removeError ? (
          <Alert variant="destructive">
            <AlertTitle>Address not removed</AlertTitle>
            <AlertDescription>{removeError}</AlertDescription>
          </Alert>
        ) : null}
        <DebouncedSearchInput
          ariaLabel="Search the Do Not Email list"
          onChange={(value) => {
            setOffset(0)
            setSearch(value)
          }}
          placeholder="Search addresses or reasons"
          value={search}
        />
        {query.isError ? (
          <EmptyState
            description={getErrorMessage(query.error)}
            icon={<MailXIcon className="size-5" />}
            size="compact"
            title="The list could not load"
          />
        ) : data && data.total === 0 ? (
          <EmptyState
            description={
              search
                ? "No addresses or reasons match your search."
                : "Add anyone who has asked not to be contacted."
            }
            icon={<MailXIcon className="size-5" />}
            size="compact"
            title={search ? "No matches" : "No one is on the list"}
          />
        ) : (
          <div aria-busy={query.isFetching} className="flex flex-col gap-3">
            <EmailSuppressionsTable
              entries={data?.entries ?? []}
              onRemove={
                canRemove
                  ? (entry) => {
                      setRemoveError(null)
                      setRemoveTarget(entry)
                    }
                  : null
              }
            />
            <PaginationControls
              ariaLabel="Do Not Email pages"
              disabled={query.isFetching}
              limit={PAGE_SIZE}
              offset={data?.offset ?? offset}
              onPageChange={setOffset}
              total={data?.total ?? 0}
            />
          </div>
        )}
      </CardContent>

      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Remove Address"
        confirmPendingLabel="Removing"
        description={
          removeTarget
            ? `Remove ${removeTarget.email}? Agents in this workspace can email them again.`
            : "Remove this address?"
        }
        isPending={removeMutation.isPending}
        onConfirm={removeEntry}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null)
        }}
        open={removeTarget !== null}
        title="Remove from Do Not Email?"
      />
    </Card>
  )
}

function AddResultAlert({ result }: { result: EmailSuppressionAddResponse }) {
  const parts = [
    `Added ${countLabel(result.added.length)}.`,
    result.already_listed.length > 0
      ? `${countLabel(result.already_listed.length)} ${result.already_listed.length === 1 ? "was" : "were"} already on the list.`
      : null,
    result.invalid.length > 0
      ? `Skipped ${result.invalid.length === 1 ? "one entry that isn't" : `${result.invalid.length.toLocaleString()} entries that aren't`} a valid address: ${result.invalid.join(", ")}.`
      : null,
  ].filter((part) => part !== null)
  return (
    <Alert>
      <AlertTitle>Do Not Email updated</AlertTitle>
      <AlertDescription className="break-all">{parts.join(" ")}</AlertDescription>
    </Alert>
  )
}

function countLabel(count: number) {
  return `${count.toLocaleString()} ${count === 1 ? "address" : "addresses"}`
}
