// apps/web/src/integrations/meta_ads/components/ad-edits.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { SwitchField, TextField } from "@/integrations/meta_ads/components/campaign-controls"
import { ChangeBanner } from "@/integrations/meta_ads/components/change-banner"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import {
  adEditRows,
  adEditSummary,
  adEditTimeZone,
  adNote,
  adSetScheduleText,
  adSettingProblem,
  adSettingTitle,
  currentAdProblems,
  editAds,
  formatAdSetting,
  type AdEdit,
  type AdEditArgs,
  type AdEditResult,
  type AdEditRow,
  type AdSettingEdit,
} from "@/integrations/meta_ads/lib/ad-edits"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

type Edit = (id: string, change: { included: boolean } | AdSettingEdit) => void

export function AdEditApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: AdEditArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: AdEditArgs
}) {
  const rows = adEditRows(proposed, args)
  const kept = rows.filter((row) => row.included).length
  const timeZone = adEditTimeZone(proposed)
  const edit: Edit = (id, change) => {
    onFieldEdit("changes", editAds(rows, id, change))
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        detail={`${String(kept)} ${pluralize(kept, "ad")}${timeZone ? ` · Times in ${timeZone}` : ""}`}
      />
      <SettingRows ariaLabel="Ads to change" defaultOpen={rows[0]?.edit.id ?? null}>
        {rows.map((row) => (
          <AdRow key={row.edit.id} disabled={disabled} edit={edit} row={row} />
        ))}
      </SettingRows>
    </div>
  )
}

function AdRow({ disabled, edit, row }: { disabled: boolean; edit: Edit; row: AdEditRow }) {
  const { edit: ad, included } = row
  const problems = included ? currentAdProblems(ad) : []
  const note = included ? adNote(ad) : null
  const href = adsManagerObjectUrl("ad", ad.accountId, ad.id)
  const schedules = ad.settings.some((setting) => setting.key !== "name")
  const adSetRuns = schedules ? adSetScheduleText(ad) : null
  const summary = !included ? "Left as it is" : (problems[0] ?? adEditSummary(ad))
  return (
    <SettingRow
      rowKey={ad.id}
      summary={summary}
      title={ad.name}
      tone={problems.length > 0 ? "error" : "neutral"}
    >
      <SwitchField
        checked={included}
        disabled={disabled}
        label="Change This Ad"
        onChange={(checked) => {
          edit(ad.id, { included: checked })
        }}
      />
      {included ? (
        <>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            {ad.settings.map((setting) => (
              <AdEditField
                key={setting.key}
                ad={ad}
                disabled={disabled}
                onChange={(value) => {
                  edit(ad.id, { key: setting.key, value })
                }}
                setting={setting}
              />
            ))}
            {adSetRuns ? (
              <div className="grid min-w-0 content-start gap-1">
                <p className="text-sm font-medium">Ad Set Runs</p>
                <p className="text-foreground/80 flex min-h-9 items-center text-sm">{adSetRuns}</p>
                <p className="text-muted-foreground text-sm">
                  The ad's times must fall inside this.
                </p>
              </div>
            ) : null}
          </div>
          {schedules ? (
            <p className="text-muted-foreground text-sm">
              Leave a time empty and the ad follows its ad set's schedule.
            </p>
          ) : null}
          {problems.map((problem) => (
            <p key={problem} className="text-destructive text-sm font-medium">
              {problem}
            </p>
          ))}
          {note ? <p className="text-foreground/75 text-sm">{note}</p> : null}
        </>
      ) : null}
      {href ? <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink> : null}
    </SettingRow>
  )
}

/** One setting's new value, with its value now and any problem with the new one. */
function AdEditField({
  ad,
  disabled,
  onChange,
  setting,
}: {
  ad: AdEdit
  disabled: boolean
  onChange: (value: string) => void
  setting: AdSettingEdit
}) {
  const title = adSettingTitle(setting.key)
  const before = ad.check?.before[setting.key] ?? null
  const problem = adSettingProblem(setting)
  const name = setting.key === "name"
  return (
    <div className={cn("grid min-w-0 content-start gap-1", name && "sm:col-span-2")}>
      {name ? (
        <TextField
          disabled={disabled}
          invalid={problem !== null}
          label={title}
          onChange={onChange}
          value={setting.value}
        />
      ) : (
        // As End Date on Edit Ad Sets: an empty field clears the ad's own time.
        <TextField
          disabled={disabled}
          invalid={problem !== null}
          label={`${title} (Optional)`}
          onChange={(value) => {
            onChange(value || "none")
          }}
          type="datetime-local"
          value={setting.value === "none" ? "" : setting.value}
        />
      )}
      <p className="text-muted-foreground text-sm">
        Current Setting: {formatAdSetting(setting.key, before)}
      </p>
      {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
    </div>
  )
}

export function AdEditOutcome({ result }: { result: AdEditResult }) {
  const rows: MetaAdsOutcomeRow[] = result.ads.flatMap((ad) =>
    ad.changes.map((change, index) => ({
      name: ad.name,
      setting: adSettingTitle(change.key),
      before: formatAdSetting(change.key, change.before),
      after:
        // Nothing was read back, so there is no value to show.
        (ad.outcome === "failed" || ad.outcome === "unverified") && change.after === null
          ? "—"
          : formatAdSetting(change.key, change.after),
      outcome: ad.outcome,
      // The ad's message once, on its first setting.
      details: index === 0 ? (ad.message ?? "") : "",
      errorCode: index === 0 ? ad.errorCode : null,
    }))
  )
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Ad" },
        { key: "setting", kind: "text", label: "Setting" },
        { key: "before", kind: "text", label: "Before" },
        { key: "after", kind: "text", label: "After" },
      ]}
      exportFilename="meta-ads-ad-changes.csv"
      rows={rows}
    />
  )
}
