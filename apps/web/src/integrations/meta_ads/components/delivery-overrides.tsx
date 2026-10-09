// apps/web/src/integrations/meta_ads/components/delivery-overrides.tsx

import { Checkbox } from "@/components/ui/checkbox"
import { ButtonSelect } from "@/integrations/meta_ads/components/button-select"
import { LabelledInput, LabelledSelect } from "@/integrations/meta_ads/components/editor-fields"
import type { CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { checksFor, type AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  blankToNull,
  editAd,
  followsShared,
  setFollowsShared,
  type EditableAdKey,
  type EditedAds,
} from "@/integrations/meta_ads/lib/create-ads-edits"

const STATUS_OPTIONS = [
  { value: "paused", label: "Paused" },
  { value: "active", label: "Active" },
] as const

/** This ad's link, CTA button, URL tags, and status: the shared ones exactly, or its own. */
export function DeliveryOverrides({
  args,
  disabled,
  id,
  onEdit,
  row,
}: {
  args: CreateAdsArgs
  disabled: boolean
  id: string
  onEdit: (ads: EditedAds) => void
  row: AdRow
}) {
  const { ad } = row
  const shared = followsShared(ad)
  const locked = disabled || shared
  const edit = (key: EditableAdKey, value: string | null) => {
    onEdit(editAd(args, ad.index, key, value))
  }
  return (
    <section
      aria-label={`Link, CTA button, URL tags and status for ${ad.name}`}
      className="grid gap-3 border-t pt-3"
    >
      <label
        className="flex w-fit cursor-pointer items-center gap-2 text-sm"
        htmlFor={`${id}-shared`}
      >
        <Checkbox
          checked={shared}
          disabled={disabled}
          id={`${id}-shared`}
          onCheckedChange={(checked) => {
            onEdit(setFollowsShared(args, ad.index, checked))
          }}
        />
        Use the link, CTA button, URL tags and status above
      </label>
      <div className="grid gap-3 @md:grid-cols-2">
        <LabelledInput
          checks={checksFor(row, "link")}
          disabled={locked}
          id={`${id}-link`}
          inputMode="url"
          label="Website Link"
          onChange={(value) => {
            edit("link", blankToNull(value))
          }}
          value={row.link ?? ""}
        />
        <LabelledInput
          checks={checksFor(row, "url_tags")}
          disabled={locked}
          id={`${id}-tags`}
          label="URL Tags"
          onChange={(value) => {
            edit("url_tags", blankToNull(value))
          }}
          placeholder="None"
          value={row.urlTags ?? ""}
        />
        <ButtonSelect
          allowed={row.allowedButtons}
          checks={checksFor(row, "call_to_action")}
          disabled={locked}
          id={`${id}-button`}
          label={`CTA button for ${ad.name}`}
          onChange={(value) => {
            edit("call_to_action", value)
          }}
          value={row.callToAction}
        />
        <LabelledSelect
          accessibleLabel={`Status for ${ad.name}`}
          disabled={locked || row.statusForced}
          id={`${id}-status`}
          label="Status"
          note={row.statusForced ? "Paused while an AI enhancement is on." : null}
          onChange={(value) => {
            edit("status", value)
          }}
          options={STATUS_OPTIONS}
          value={row.status}
        />
      </div>
    </section>
  )
}
