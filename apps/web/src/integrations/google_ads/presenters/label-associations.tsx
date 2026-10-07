// apps/web/src/integrations/google_ads/presenters/label-associations.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { GoogleAdsLabelAssociationSummary } from "@/integrations/google_ads/components/label-association-summary"
import { GoogleAdsLabelChip } from "@/integrations/google_ads/components/label-chip"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import {
  LABEL_TARGET_KIND_LABELS,
  LABEL_TARGET_KINDS,
  labelColor,
  parseLabelAssociationArgs,
  type LabelAssociationArgs,
  type LabelTargetKind,
} from "@/integrations/google_ads/lib/labels"
import { countByKind, rowsPartlyFailed } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isOneOf, isRecord } from "@/lib/guards"

type Action = "apply" | "remove"

const OUTCOMES = {
  apply: new Set(["applied", "already_applied", "failed", "unverified"] as const),
  remove: new Set(["removed", "not_applied", "failed", "unverified"] as const),
}
const TARGET_KINDS = new Set(LABEL_TARGET_KINDS)

type AssociationRow = GoogleAdsOutcomeRow & {
  kind: string
  labelColor: string | null
  labelId: string
  labelName: string
  targetId: string
  targetKind: LabelTargetKind
  targetName: string
}

export const googleAdsLabelAssociationsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_apply_labels: defineIntegrationWriteVariant(
      googleAdsProvider,
      labelAssociationSpec("apply")
    ),
    google_ads_remove_labels: defineIntegrationWriteVariant(
      googleAdsProvider,
      labelAssociationSpec("remove")
    ),
  },
})

function labelAssociationSpec(
  action: Action
): IntegrationWriteVariant<LabelAssociationArgs, AssociationRow[]> {
  return {
    copy:
      action === "apply"
        ? { verb: "Apply", object: "labels", effect: "applied" }
        : { verb: "Remove", object: "labels", effect: "removed" },
    approval: {
      parseArgs: parseLabelAssociationArgs,
      prompt:
        action === "apply"
          ? "Review which items each label will be attached to."
          : "Review which items each label will be detached from. The labels stay in the account.",
      renderFields: false,
      renderSummary: (value, fallback) => (
        <GoogleAdsLabelAssociationSummary args={parseLabelAssociationArgs(value) ?? fallback} />
      ),
    },
    details: (args) =>
      args
        ? [
            { label: "Labels", value: args.labels.map((label) => label.name).join(", ") },
            { label: "Items", value: String(args.targets.length) },
          ]
        : [],
    settledPartial: rowsPartlyFailed,
    parseResult: (value) => parseAssociationResult(value, action),
    renderFailure: (args, description) => (
      <GoogleAdsFailureTargets
        description={description}
        targets={args?.targets.map((target) => target.name) ?? []}
      />
    ),
    renderOutcome: renderAssociationOutcome,
    renderUnverifiedOutcome: renderAssociationOutcome,
  }
}

function renderAssociationOutcome(rows: AssociationRow[]) {
  const sorted = LABEL_TARGET_KINDS.flatMap((kind) => rows.filter((row) => row.targetKind === kind))
  return (
    <GoogleAdsOutcomeTable
      columns={[
        { key: "kind", kind: "text", label: "Type" },
        { key: "targetName", kind: "text", label: "Item" },
        { key: "labelName", kind: "text", label: "Label" },
      ]}
      rows={sorted}
      outcomes={countByKind(rows)}
      exportFilename="google-ads-label-changes.csv"
      renderCell={(column, row) =>
        column.key === "labelName" ? (
          <GoogleAdsLabelChip
            name={String(row["labelName"])}
            color={labelColor(row["labelColor"])}
          />
        ) : null
      }
    />
  )
}

function parseAssociationResult(value: unknown, action: Action) {
  return parseOutcomeList(
    value,
    "associations",
    (row) => parseAssociationRow(row, action),
    (row) => `${row.labelId}:${row.targetKind}:${row.targetId}`
  )
}

function parseAssociationRow(value: unknown, action: Action): AssociationRow | null {
  if (
    !isRecord(value) ||
    typeof value["label_id"] !== "string" ||
    typeof value["label_name"] !== "string" ||
    typeof value["target_id"] !== "string" ||
    typeof value["target_name"] !== "string" ||
    !isOneOf(TARGET_KINDS, value["target_kind"])
  )
    return null
  const outcome = value["outcome"]
  if (!isOneOf(OUTCOMES[action], outcome)) return null
  const failed = outcome === "failed" || outcome === "unverified"
  return {
    kind: LABEL_TARGET_KIND_LABELS[value["target_kind"]],
    labelColor: labelColor(value["label_color"]),
    labelId: value["label_id"],
    labelName: value["label_name"],
    targetId: value["target_id"],
    targetKind: value["target_kind"],
    targetName: value["target_name"],
    outcome,
    details: failed
      ? typeof value["message"] === "string"
        ? value["message"]
        : "Google Ads didn't confirm this change."
      : "",
    errorCode: failed && typeof value["error_code"] === "string" ? value["error_code"] : "",
  }
}
