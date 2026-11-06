// apps/web/src/integrations/meta_ads/components/ad-creative-edit.tsx

import { AdEditor } from "@/integrations/meta_ads/components/ad-editor"
import { AdPreview } from "@/integrations/meta_ads/components/ad-preview"
import {
  changedFields,
  creativeChanges,
  creativeEditorArgs,
  creativeFieldTitle,
  creativeMediaProblem,
  creativeAfter,
} from "@/integrations/meta_ads/lib/ad-creative-edits"
import { adCreativeArgs, type AdEdit } from "@/integrations/meta_ads/lib/ad-edits"
import { adPreviewProps, adRows } from "@/integrations/meta_ads/lib/create-ads-checks"
import { editAd, type EditedAds } from "@/integrations/meta_ads/lib/create-ads-edits"
import { isRecord } from "@/lib/guards"

/** The ad's new creative: what changes, the ad now and after, and the editor for the new one. */
export function AdCreativeEdit({
  ad,
  catalogue,
  disabled,
  onChange,
}: {
  ad: AdEdit
  catalogue: unknown
  disabled: boolean
  onChange: (creative: Record<string, unknown>, name: string | null) => void
}) {
  const check = ad.check?.creative
  const args = adCreativeArgs(ad, catalogue)
  const row = args ? adRows(args)[0] : undefined
  if (!check || !ad.creative || !args || !row) {
    return (
      <p className="text-foreground/75 text-sm">
        The ad's current creative couldn't be read, so Meta checks the new one when you approve.
      </p>
    )
  }
  const proposed = ad.creative
  const before = creativeEditorArgs({
    accountId: ad.accountId,
    after: check.content,
    catalogue,
    check,
    name: ad.check?.before.name ?? ad.name,
  })
  const beforeRow = before ? adRows(before)[0] : undefined
  const changed = changedFields(ad.creative)
  const mediaProblem = creativeMediaProblem(creativeAfter(check, ad.creative))
  const edit = (ads: EditedAds) => {
    const edited = ads[0]
    if (!isRecord(edited)) return
    // The editor's name field renames the ad only when the agent proposed a new name.
    const name = typeof edited["name"] === "string" ? edited["name"] : null
    onChange(creativeChanges(check, edited, proposed), name)
  }
  return (
    <div className="grid min-w-0 gap-4">
      <p className="text-sm">
        <span className="font-medium">New Creative: </span>
        {changed.length > 0
          ? changed.map(creativeFieldTitle).join(", ")
          : "Matches the current version"}
      </p>
      {before && beforeRow && !row.ad.post ? (
        <div className="flex flex-wrap items-start justify-center gap-4">
          <div className="grid w-60 gap-1.5">
            <p className="text-center text-sm font-medium">Now</p>
            <AdPreview {...adPreviewProps(before, beforeRow)} placement="feed" />
          </div>
          <div className="grid w-60 gap-1.5">
            <p className="text-center text-sm font-medium">After Approval</p>
            <AdPreview {...adPreviewProps(args, row)} placement="feed" />
          </div>
        </div>
      ) : null}
      <AdEditor
        args={args}
        count={1}
        disabled={disabled}
        onEdit={edit}
        onEditSetting={(key, value) => {
          edit(editAd(args, 0, key, value))
        }}
        onSelect={() => undefined}
        renderAdSets={() => (
          <p className="text-foreground/80 flex min-h-9 items-center text-sm">
            {args.adSets.values().next().value?.name ?? "This ad's ad set"}
          </p>
        )}
        row={row}
      />
      {mediaProblem ? <p className="text-destructive text-sm font-medium">{mediaProblem}</p> : null}
      {check.notes.length > 0 ? (
        <ul className="text-foreground/75 grid list-disc gap-1 pl-5 text-sm">
          {check.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
