// apps/web/src/integrations/meta_ads/components/ad-set-edits.tsx

import { TriangleAlertIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { AdSetEditField } from "@/integrations/meta_ads/components/ad-set-edit-field"
import { SwitchField } from "@/integrations/ads/components/controls"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import {
  adSetEditRows,
  adSetLabels,
  adSetNotes,
  adSetSummary,
  adSetWarnings,
  currentProblems,
  editAdSets,
  editStrategy,
  formatSettingValue,
  settingTitle,
  type AdSetEditArgs,
  type AdSetEditResult,
  type AdSetEditRow,
  type SettingChange,
} from "@/integrations/meta_ads/lib/ad-set-edits"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { pluralize } from "@/lib/format"

type Edit = (id: string, change: { included: boolean } | SettingChange) => void

export function AdSetEditApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: AdSetEditArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: AdSetEditArgs
}) {
  const rows = adSetEditRows(proposed, args)
  const kept = rows.filter((row) => row.included).length
  const edit: Edit = (id, change) => {
    onFieldEdit("changes", editAdSets(rows, id, change))
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner detail={`${String(kept)} ${pluralize(kept, "ad set")}`} />
      <SettingRows ariaLabel="Ad sets to change" defaultOpen={rows[0]?.edit.id ?? null}>
        {rows.map((row) => (
          <AdSetRow key={row.edit.id} disabled={disabled} edit={edit} row={row} />
        ))}
      </SettingRows>
    </div>
  )
}

function AdSetRow({ disabled, edit, row }: { disabled: boolean; edit: Edit; row: AdSetEditRow }) {
  const { edit: adSet, included } = row
  const problems = included ? currentProblems(adSet) : []
  const strategy = editStrategy(adSet)
  const labels = adSetLabels(adSet)
  const href = adsManagerObjectUrl("adset", adSet.accountId, adSet.id)
  const summary = !included ? "Left as it is" : (problems[0] ?? adSetSummary(adSet, strategy))
  return (
    <SettingRow
      rowKey={adSet.id}
      summary={summary}
      title={adSet.name}
      tone={problems.length > 0 ? "error" : "neutral"}
    >
      <SwitchField
        checked={included}
        disabled={disabled}
        label="Change This Ad Set"
        onChange={(checked) => {
          edit(adSet.id, { included: checked })
        }}
      />
      {included ? (
        <>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            {adSet.settings.map((setting) => (
              <AdSetEditField
                key={setting.key}
                adSet={adSet}
                disabled={disabled}
                labels={labels}
                onChange={(change) => {
                  edit(adSet.id, change)
                }}
                setting={setting}
                strategy={strategy}
              />
            ))}
          </div>
          {problems.map((problem) => (
            <p key={problem} className="text-destructive text-sm font-medium">
              {problem}
            </p>
          ))}
          {adSetWarnings(adSet).map((warning) => (
            <p key={warning} className="text-warning-text flex items-start gap-2 text-sm">
              <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {warning}
            </p>
          ))}
          {adSetNotes(adSet).map((note) => (
            <p key={note} className="text-foreground/75 text-sm">
              {note}
            </p>
          ))}
        </>
      ) : null}
      {href ? <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink> : null}
    </SettingRow>
  )
}

export function AdSetEditOutcome({ result }: { result: AdSetEditResult }) {
  const rows: MetaAdsOutcomeRow[] = result.adSets.flatMap((adSet) => {
    const strategy = adSet.changes.find((change) => change.key === "bid_strategy")?.requested
    return adSet.changes.map((change, index) => ({
      name: adSet.name,
      setting: settingTitle(change.key, strategy ?? null),
      before: formatSettingValue(change.key, change.before, result.currency, adSet.labels),
      after:
        // Nothing was read back, so there is no value to show.
        (adSet.outcome === "failed" || adSet.outcome === "unverified") && change.after === null
          ? "—"
          : formatSettingValue(change.key, change.after, result.currency, adSet.labels),
      outcome: adSet.outcome,
      // The ad set's message once, on its first setting.
      details: index === 0 ? (adSet.message ?? "") : "",
      errorCode: index === 0 ? adSet.errorCode : null,
    }))
  })
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Ad Set" },
        { key: "setting", kind: "text", label: "Setting" },
        { key: "before", kind: "text", label: "Before" },
        { key: "after", kind: "text", label: "After" },
      ]}
      exportFilename="meta-ads-ad-set-changes.csv"
      rows={rows}
    />
  )
}
