// apps/web/src/features/knowledge/components/integration-import-review.tsx

import type { SyntheticEvent } from "react"
import { ArrowLeftIcon, ExternalLinkIcon } from "lucide-react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Button } from "@/components/ui/button"
import { DialogClose, DialogFooter } from "@/components/ui/dialog"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import type { KbIntegrationSourcePreview } from "@/features/knowledge/types"
import type { FormValidationEntry } from "@/lib/forms"

export function IntegrationImportReview({
  error,
  errorTitle,
  isPending,
  isPrivate,
  onBack,
  onIsPrivateChange,
  onSubmit,
  onTitleChange,
  preview,
  title,
  validationEntries,
}: {
  error: string | null
  errorTitle: string
  isPending: boolean
  isPrivate: boolean
  onBack: () => void
  onIsPrivateChange: (isPrivate: boolean) => void
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void
  onTitleChange: (title: string) => void
  preview: KbIntegrationSourcePreview
  title: string
  validationEntries: readonly FormValidationEntry[]
}) {
  return (
    <form className="flex min-h-0 min-w-0 flex-col gap-5" onSubmit={onSubmit}>
      <FormAlerts error={error} errorTitle={errorTitle} validationEntries={validationEntries} />
      <Button
        className="w-fit"
        disabled={isPending}
        onClick={onBack}
        size="sm"
        type="button"
        variant="ghost"
      >
        <ArrowLeftIcon data-icon="inline-start" />
        Back to sources
      </Button>
      <section className="flex min-w-0 flex-col gap-2">
        <div>
          <h3 className="font-medium">Source preview</h3>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Confirm that this is the source you want to import.
          </p>
        </div>
        <div className="bg-muted/25 flex min-w-0 flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h4 className="truncate font-medium">{preview.title}</h4>
              <p className="text-muted-foreground truncate text-xs">{preview.url}</p>
            </div>
            <a
              aria-label={`Open ${preview.title} in a new tab`}
              className="text-muted-foreground hover:text-foreground shrink-0"
              href={preview.url}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLinkIcon className="size-4" />
            </a>
          </div>
          <p className="text-muted-foreground max-h-36 overflow-y-auto border-t pt-3 text-sm whitespace-pre-wrap">
            {preview.markdown_excerpt || "This page has no previewable text."}
          </p>
        </div>
      </section>
      <section className="flex min-w-0 flex-col gap-3">
        <div>
          <h3 className="font-medium">Import settings</h3>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Choose how the source appears and who can search it.
          </p>
        </div>
        <Field>
          <FieldLabel htmlFor="knowledge-integration-title">Knowledge Base title</FieldLabel>
          <Input
            disabled={isPending}
            id="knowledge-integration-title"
            maxLength={500}
            onChange={(event) => {
              onTitleChange(event.target.value)
            }}
            value={title}
          />
        </Field>
        <PrivacyField
          checked={isPrivate}
          onCheckedChange={onIsPrivateChange}
          sharedDescription="Anyone in this workspace can search the page content."
        />
      </section>
      <DialogFooter className="mx-0 mb-0 min-w-0 rounded-lg">
        <DialogClose render={<Button disabled={isPending} variant="outline" />}>Cancel</DialogClose>
        <Button disabled={isPending} type="submit">
          {isPending ? "Importing…" : "Import page"}
        </Button>
      </DialogFooter>
    </form>
  )
}
