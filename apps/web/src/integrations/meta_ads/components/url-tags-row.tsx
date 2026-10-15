// apps/web/src/integrations/meta_ads/components/url-tags-row.tsx

import { Checkbox } from "@/components/ui/checkbox"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import { SettingRow } from "@/integrations/meta_ads/components/setting-rows"
import type { CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { checksFor, hasError, type AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  blankToNull,
  followsShared,
  setFollowsShared,
  type EditedAds,
} from "@/integrations/meta_ads/lib/create-ads-edits"

/** URL tags for the open ad, and whether it keeps its own link, button, and tags. */
export function UrlTagsRow({
  args,
  disabled,
  id,
  onEdit,
  onEditSetting,
  row,
}: {
  args: CreateAdsArgs
  disabled: boolean
  id: string
  onEdit: (ads: EditedAds) => void
  onEditSetting: (key: "url_tags", value: string | null) => void
  row: AdRow
}) {
  const { ad } = row
  const checks = checksFor(row, "url_tags")
  const own = !followsShared(ad)
  return (
    <SettingRow
      rowKey="url-tags"
      summary={checks[0]?.message ?? row.urlTags ?? "None"}
      title="URL Tags"
      tone={hasError(checks) ? "error" : "neutral"}
    >
      <LabelledInput
        checks={checks}
        disabled={disabled}
        hint={
          args.ads.length > 1 && !own ? `shared by all ${String(args.ads.length)} ads` : undefined
        }
        id={`${id}-tags`}
        label="URL Tags"
        onChange={(value) => {
          onEditSetting("url_tags", blankToNull(value))
        }}
        placeholder="None"
        value={row.urlTags ?? ""}
      />
      {args.ads.length > 1 ? (
        <label
          className="flex w-fit cursor-pointer items-center gap-2 text-sm"
          htmlFor={`${id}-own`}
        >
          <Checkbox
            checked={own}
            disabled={disabled}
            id={`${id}-own`}
            onCheckedChange={(checked) => {
              onEdit(setFollowsShared(args, ad.index, !checked))
            }}
          />
          Give this ad its own link, button and tags
        </label>
      ) : null}
    </SettingRow>
  )
}
