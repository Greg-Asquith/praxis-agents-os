// apps/web/src/integrations/meta_ads/components/launch-ad-set.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Checkbox } from "@/components/ui/checkbox"
import { AdEditor } from "@/integrations/meta_ads/components/ad-editor"
import { CreateAdSetApproval } from "@/integrations/meta_ads/components/ad-set-summary"
import { SettingRow } from "@/integrations/meta_ads/components/setting-rows"
import { AdsList } from "@/integrations/meta_ads/components/ads-list"
import {
  adSetBlockSummary,
  adSetEdit,
  adSetProblem,
  adsEdit,
  launchSettingEdit,
  type LaunchArgs,
} from "@/integrations/meta_ads/lib/launch-model"
import type { AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  setAdSets,
  type EditedAds,
  type SharedKey,
} from "@/integrations/meta_ads/lib/create-ads-edits"

export type SelectedAd = { key: string; index: number }

/** One ad set's settings, then the ads that go in it. */
export function LaunchAdSetBlock({
  args,
  disabled,
  keyOf,
  onEdit,
  onSelect,
  rowKey,
  rows,
  selected,
}: {
  args: LaunchArgs
  disabled: boolean
  keyOf: string
  rowKey: string
  onEdit: (edits: Record<string, EditedValue>) => void
  onSelect: (selected: SelectedAd) => void
  rows: readonly AdRow[]
  selected: SelectedAd | null
}) {
  const adSet = args.adSets.find((item) => item.key === keyOf)
  if (!adSet) return null
  const blockRows = rows.filter((row) => row.ad.adSetIds.includes(keyOf))
  const open =
    selected?.key === keyOf ? blockRows.find((row) => row.ad.index === selected.index) : null
  const problem =
    adSetProblem(args, keyOf) ?? blockRows.find((row) => row.check === "error")?.checks[0]?.message
  const editAds = (ads: EditedAds) => {
    onEdit(adsEdit(ads))
  }
  return (
    <SettingRow
      rowKey={rowKey}
      summary={problem ?? adSetBlockSummary(args, keyOf)}
      title={adSet.args.name || "Unnamed ad set"}
      tone={problem ? "error" : "neutral"}
    >
      <CreateAdSetApproval
        args={adSet.args}
        disabled={disabled}
        embedded
        onEdit={(edits) => {
          onEdit(adSetEdit(args, keyOf, edits))
        }}
      />
      <AdsList
        args={args.ads}
        onSelect={(index) => {
          onSelect({ key: keyOf, index })
        }}
        rows={[...blockRows]}
        selected={open?.ad.index ?? -1}
      />
      {open ? (
        <AdEditor
          key={open.ad.index}
          args={args.ads}
          count={1}
          disabled={disabled}
          onEdit={editAds}
          onEditSetting={(key: SharedKey, value) => {
            onEdit(launchSettingEdit(args, open.ad.index, key, value))
          }}
          onSelect={() => undefined}
          renderAdSets={(row, id) => (
            <LaunchAdSetPicker
              adSets={args.adSets.map((item) => ({ key: item.key, name: item.args.name }))}
              disabled={disabled}
              id={id}
              onChange={(keys) => {
                editAds(
                  setAdSets(
                    args.ads,
                    row.ad.index,
                    keys.map((key) => ({ adset_id: key }))
                  )
                )
              }}
              selected={row.ad.adSetIds}
            />
          )}
          row={open}
        />
      ) : null}
    </SettingRow>
  )
}

/** The ad sets an ad is created in, as checkboxes; an ad always keeps at least one. */
function LaunchAdSetPicker({
  adSets,
  disabled,
  id,
  onChange,
  selected,
}: {
  adSets: readonly { key: string; name: string }[]
  disabled: boolean
  id: string
  onChange: (keys: string[]) => void
  selected: readonly string[]
}) {
  return (
    <div aria-label="Ad sets for this ad" className="grid gap-1.5" id={id} role="group">
      {adSets.map((adSet) => {
        const checked = selected.includes(adSet.key)
        return (
          <label key={adSet.key} className="flex min-h-8 cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={checked}
              disabled={disabled || (checked && selected.length === 1)}
              onCheckedChange={(next) => {
                onChange(
                  adSets
                    .map((item) => item.key)
                    .filter((key) => (key === adSet.key ? next : selected.includes(key)))
                )
              }}
            />
            <span className="wrap-anywhere">{adSet.name}</span>
          </label>
        )
      })}
    </div>
  )
}
