// apps/web/src/integrations/google_ads/presenters/delete-labels.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { GoogleAdsLabelChip } from "@/integrations/google_ads/components/label-chip"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import {
  labelAssociationCountsText,
  labelColor,
  parseLabelAssociationCounts,
  parseLabelDeletionArgs,
  type LabelDeletionSelection,
} from "@/integrations/google_ads/lib/labels"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isOneOf, isRecord } from "@/lib/guards"

const OUTCOMES = new Set(["deleted", "failed", "unverified"] as const)

type DeleteLabelRow = GoogleAdsOutcomeRow & {
  associations: string
  color: string | null
  labelId: string
  name: string
}

export const googleAdsDeleteLabelsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_delete_labels: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Delete", object: "labels", effect: "deleted", destructive: true },
      approval: {
        parseArgs: parseLabelDeletionArgs,
        prompt: "Deleting a label also detaches it from every item listed. This can't be undone.",
        renderSummary: (value, fallback) =>
          renderDeletionSummary(parseLabelDeletionArgs(value)?.labels ?? fallback.labels),
      },
      details: (args) =>
        args ? [{ label: "Labels", value: args.labels.map((label) => label.name).join(", ") }] : [],
      parseResult: deleteLabelResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.labels.map((label) => label.name) ?? []}
        />
      ),
      renderOutcome: renderDeletionOutcome,
      renderUnverifiedOutcome: renderDeletionOutcome,
    }),
  },
})

function renderDeletionSummary(labels: LabelDeletionSelection[]) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Labels selected for permanent deletion"
      tone="destructive"
      countLine={approvalCountLine(labels.length, "label")}
    >
      {labels.map((label) => (
        <GoogleAdsEntityCard
          key={label.labelId}
          title={<GoogleAdsLabelChip name={label.name} color={label.color} />}
          meta={
            label.counts
              ? labelAssociationCountsText(label.counts)
              : "Couldn't read the items this label is attached to"
          }
        />
      ))}
    </GoogleAdsApprovalSection>
  )
}

function renderDeletionOutcome(rows: DeleteLabelRow[]) {
  return (
    <GoogleAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Label" },
        { key: "associations", kind: "text", label: "Attached Items" },
      ]}
      rows={rows}
      outcomes={countByKind(rows)}
      exportFilename="deleted-google-ads-labels.csv"
      renderCell={(column, row) =>
        column.key === "name" ? (
          <GoogleAdsLabelChip name={String(row["name"])} color={labelColor(row["color"])} />
        ) : null
      }
    />
  )
}

function deleteLabelResult(value: unknown) {
  return parseOutcomeList(value, "labels", deleteLabelRow, (row) => row.labelId)
}

function deleteLabelRow(value: unknown): DeleteLabelRow | null {
  if (
    !isRecord(value) ||
    typeof value["label_id"] !== "string" ||
    typeof value["label_name"] !== "string"
  )
    return null
  const outcome = value["outcome"]
  const counts = parseLabelAssociationCounts(value["association_counts"])
  if (!isOneOf(OUTCOMES, outcome) || counts === null) return null
  const failed = outcome !== "deleted"
  return {
    labelId: value["label_id"],
    name: value["label_name"],
    color: labelColor(value["label_color"]),
    associations: labelAssociationCountsText(counts),
    outcome,
    details: failed
      ? typeof value["message"] === "string"
        ? value["message"]
        : "Google Ads didn't confirm this deletion."
      : "",
    errorCode: failed && typeof value["error_code"] === "string" ? value["error_code"] : "",
  }
}
