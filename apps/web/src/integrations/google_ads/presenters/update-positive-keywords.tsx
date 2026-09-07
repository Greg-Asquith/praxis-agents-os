// apps/web/src/integrations/google_ads/presenters/update-positive-keywords.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { UpdatePositiveKeywordsApproval } from "@/integrations/google_ads/components/update-positive-keywords-approval"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import { outcomeKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import {
  POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY,
  formatPositiveKeywordValue,
  mutableStateFromReference,
  type MutableKeywordState,
  type PatchField,
  OUTCOMES,
  parsePatchDraft,
  updateKeywordArgs,
  updateKeywordArgsValidationError,
  updateKeywordResult,
  type UpdateKeywordResult,
} from "@/integrations/google_ads/lib/positive-keyword-update"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"

const COLUMNS: DataColumn[] = [
  { key: "scope", kind: "text", label: "Campaign · Ad Group" },
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "text", label: "Match Type" },
  { key: "fields", kind: "text", label: "Changed Fields", width: 220 },
  { key: "before", kind: "text", label: "Before", width: 320 },
  { key: "requested", kind: "text", label: "Requested", width: 320 },
  { key: "after", kind: "text", label: "After", width: 320 },
]

const copy = googleAdsWriteCopy({ verb: "Update", object: "keywords", effect: "updated" })

export const googleAdsUpdatePositiveKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-positive-keywords",
  variants: {
    google_ads_update_keywords: defineGoogleAdsWriteVariant({
      ...copy,
      approval: {
        ...copy.approval,
        parseArgs: updateKeywordArgs,
        validateArgs: updateKeywordArgsValidationError,
        prompt: "Review every changed keyword setting. Keyword text and match type stay unchanged.",
        renderFields: false,
        renderInvalidDraft: true,
        renderSummary: (value, _fallback, onFieldEdit, disabled) => {
          const args = updateKeywordArgs(value, parsePatchDraft)
          return args ? (
            <UpdatePositiveKeywordsApproval
              args={args}
              disabled={disabled}
              onChange={(patches) => {
                onFieldEdit("patches", patches)
              }}
            />
          ) : null
        },
      },
      details: (args) => (args ? [{ label: "Keywords", value: String(args.keywords.length) }] : []),
      parseResult: updateKeywordResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.keywords.map((item) => item.label) ?? []}
        />
      ),
      renderOutcome,
    }),
  },
})

function renderOutcome(result: UpdateKeywordResult) {
  const rows = result.rows.map<GoogleAdsOutcomeRow>((row) => ({
    requested: summarizeFields(row.requested, row.requestedFields, result.currencyCode),
    after:
      row.outcome === "updated" || row.outcome === "already_set"
        ? summarizeFields(
            mutableStateFromReference(row.reference),
            row.requestedFields,
            result.currencyCode
          )
        : "Unverified",
    before: summarizeFields(row.before, row.requestedFields, result.currencyCode),
    details: row.message ?? "",
    fields: row.requestedFields.map(fieldLabel).join(", "),
    keyword: row.reference.text,
    matchType: googleAdsTokenLabel(row.reference.matchType, row.reference.matchType),
    outcome: row.outcome,
    errorCode: row.errorCode,
    scope: row.reference.scopeLabel,
  }))
  return (
    <GoogleAdsOutcomeTable
      columns={COLUMNS}
      exportFilename="google-ads-keyword-updates.csv"
      outcomes={OUTCOMES.map((outcome) => ({
        kind: outcomeKind(outcome),
        label: outcomeLabel(outcome),
        count: result.counts[outcome],
      }))}
      rows={rows}
    />
  )
}

function summarizeFields(
  state: MutableKeywordState,
  fields: PatchField[],
  currencyCode: string
): string {
  return fields
    .map((field) => {
      return `${fieldLabel(field)}: ${formatPositiveKeywordValue(field, state[field], currencyCode)}`
    })
    .join(" · ")
}

function fieldLabel(field: PatchField): string {
  return POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)?.label ?? googleAdsTokenLabel(field, field)
}
