// apps/web/src/integrations/meta_ads/components/ad-set-edits.tsx

import { TriangleAlertIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { ChangeBanner } from "@/integrations/meta_ads/components/change-banner"
import {
  SelectField,
  SwitchField,
  TextField,
} from "@/integrations/meta_ads/components/campaign-controls"
import { MoneyField } from "@/integrations/meta_ads/components/campaign-money-field"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import {
  adSetEditRows,
  adSetNotes,
  adSetSummary,
  adSetWarnings,
  currentProblems,
  editAdSets,
  editStrategy,
  formatSettingValue,
  settingKind,
  settingChange,
  settingProblem,
  settingTitle,
  settingUnit,
  type AdSetEditArgs,
  type AdSetEditResult,
  type AdSetEditRow,
  type SettingEdit,
} from "@/integrations/meta_ads/lib/ad-set-edits"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { BID_OPTIONS } from "@/integrations/meta_ads/lib/create-campaign"
import { pluralize } from "@/lib/format"

type Edit = (id: string, change: { included: boolean } | SettingEdit) => void

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
  const { edit: change, included } = row
  const problems = included ? currentProblems(change) : []
  const currency = change.check?.currency ?? null
  const before = change.check?.before ?? {}
  const strategy = editStrategy(change)
  const href = adsManagerObjectUrl("adset", change.accountId, change.id)
  const summary = !included ? "Left as it is" : (problems[0] ?? adSetSummary(change, strategy))
  return (
    <SettingRow
      rowKey={change.id}
      summary={summary}
      title={change.name}
      tone={problems.length > 0 ? "error" : "neutral"}
    >
      <SwitchField
        checked={included}
        disabled={disabled}
        label="Change This Ad Set"
        onChange={(checked) => {
          edit(change.id, { included: checked })
        }}
      />
      {included ? (
        <>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            {change.settings.map((setting) => {
              const previous = before[setting.key] ?? null
              const percent = settingChange(setting, previous)
              return (
                <div key={setting.key} className="grid min-w-0 gap-1">
                  <SettingField
                    currency={currency}
                    disabled={disabled}
                    label={settingTitle(setting.key, strategy)}
                    onChange={(value) => {
                      edit(change.id, { key: setting.key, value })
                    }}
                    setting={setting}
                  />
                  <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
                    Current Setting: {formatSettingValue(setting.key, previous, currency)}
                    {percent ? (
                      <Badge
                        variant={Number(setting.value) < Number(previous) ? "secondary" : "success"}
                      >
                        {percent}
                      </Badge>
                    ) : null}
                  </p>
                  {settingProblem(setting) ? (
                    <p className="text-destructive text-sm">{settingProblem(setting)}</p>
                  ) : null}
                </div>
              )
            })}
          </div>
          {problems.map((problem) => (
            <p key={problem} className="text-destructive text-sm font-medium">
              {problem}
            </p>
          ))}
          {adSetWarnings(change).map((warning) => (
            <p key={warning} className="text-warning-text flex items-start gap-2 text-sm">
              <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {warning}
            </p>
          ))}
          {adSetNotes(change).map((note) => (
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

/** The create card's field for one new value; an optional one left empty clears the setting. */
function SettingField({
  currency,
  disabled,
  label,
  onChange,
  setting,
}: {
  currency: string | null
  disabled: boolean
  label: string
  onChange: (value: string) => void
  setting: SettingEdit
}) {
  const kind = settingKind(setting.key)
  const invalid = settingProblem(setting) !== null
  if (kind === "bid")
    return (
      <SelectField
        disabled={disabled}
        label={label}
        onChange={onChange}
        options={BID_OPTIONS}
        value={setting.value}
      />
    )
  if (kind === "money" || kind === "ratio")
    return (
      <MoneyField
        currency={kind === "ratio" ? null : currency}
        disabled={disabled}
        invalid={invalid}
        label={label}
        onChange={onChange}
        suffix={settingUnit(setting.key)}
        value={setting.value}
      />
    )
  if (kind === "limit")
    return (
      <MoneyField
        currency={currency}
        disabled={disabled}
        invalid={invalid}
        label={`${label} (Optional)`}
        onChange={(value) => {
          onChange(value || "remove")
        }}
        placeholder="No limit"
        suffix={settingUnit(setting.key)}
        value={setting.value === "remove" ? "" : setting.value}
      />
    )
  if (kind === "end")
    return (
      <TextField
        disabled={disabled}
        invalid={invalid}
        label={`${label} (Optional)`}
        onChange={(value) => {
          onChange(value || "none")
        }}
        type="date"
        value={setting.value === "none" ? "" : setting.value}
      />
    )
  return (
    <TextField
      disabled={disabled}
      invalid={invalid}
      label={label}
      onChange={onChange}
      type={kind === "date" ? "date" : "text"}
      value={setting.value}
    />
  )
}

export function AdSetEditOutcome({ result }: { result: AdSetEditResult }) {
  const rows: MetaAdsOutcomeRow[] = result.adSets.flatMap((adSet) => {
    const strategy = adSet.changes.find((change) => change.key === "bid_strategy")?.requested
    return adSet.changes.map((change, index) => ({
      name: adSet.name,
      setting: settingTitle(change.key, strategy ?? null),
      before: formatSettingValue(change.key, change.before, result.currency),
      after:
        // Nothing was read back, so there is no value to show.
        (adSet.outcome === "failed" || adSet.outcome === "unverified") && change.after === null
          ? "—"
          : formatSettingValue(change.key, change.after, result.currency),
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
