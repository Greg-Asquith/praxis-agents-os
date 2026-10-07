// apps/web/src/integrations/google_ads/presenters/create-labels.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import { GoogleAdsLabelChip } from "@/integrations/google_ads/components/label-chip"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import {
  isLabelReference,
  labelColor,
  labelDraftsValidationError,
  labelNameKey,
  parseLabelDrafts,
  type GoogleAdsLabelDraft,
} from "@/integrations/google_ads/lib/labels"
import { countByKind, rowsPartlyFailed } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isOneOf, isRecord } from "@/lib/guards"

const OUTCOMES = new Set(["created", "already_exists", "failed", "unverified"] as const)

type CreateLabelRow = GoogleAdsOutcomeRow & {
  color: string | null
  description: string
  name: string
}

export const googleAdsCreateLabelsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_labels: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Create", object: "labels", effect: "created" },
      approval: {
        parseArgs: createLabelArgs,
        validateArgs: (value) => {
          const drafts = isRecord(value) ? parseLabelDrafts(value["labels"]) : null
          return drafts ? labelDraftsValidationError(drafts) : null
        },
        renderSummary: (value, fallback) => {
          const args = createLabelArgs(value) ?? fallback
          return (
            <GoogleAdsApprovalSection
              ariaLabel="Proposed labels"
              countLine={approvalCountLine(args.labels.length, "label")}
            >
              {args.labels.map((label) => (
                <GoogleAdsEntityCard
                  key={label.name}
                  title={
                    <GoogleAdsLabelChip
                      name={label.name}
                      color={labelColor(label.backgroundColor)}
                    />
                  }
                  meta={label.description}
                />
              ))}
            </GoogleAdsApprovalSection>
          )
        },
        prompt: "Review each label before creating it in the selected accounts.",
      },
      details: (args) =>
        args ? [{ label: "Labels", value: args.labels.map((label) => label.name).join(", ") }] : [],
      settledPartial: rowsPartlyFailed,
      parseResult: createLabelResult,
      renderOutcome: renderLabelOutcome,
      renderUnverifiedOutcome: renderLabelOutcome,
    }),
  },
})

function renderLabelOutcome(rows: CreateLabelRow[]) {
  return (
    <GoogleAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Label" },
        { key: "description", kind: "text", label: "Description" },
      ]}
      rows={rows}
      outcomes={countByKind(rows)}
      exportFilename="google-ads-labels.csv"
      renderCell={(column, row) =>
        column.key === "name" ? (
          <GoogleAdsLabelChip name={String(row["name"])} color={labelColor(row["color"])} />
        ) : null
      }
    />
  )
}

function createLabelArgs(value: unknown): { labels: GoogleAdsLabelDraft[] } | null {
  const labels = isRecord(value) ? parseLabelDrafts(value["labels"]) : null
  return labels ? { labels } : null
}

function createLabelResult(value: unknown) {
  return parseOutcomeList(value, "labels", createLabelRow, (row) => labelNameKey(row.name))
}

function createLabelRow(value: unknown): CreateLabelRow | null {
  if (!isRecord(value) || typeof value["name"] !== "string") return null
  const outcome = value["outcome"]
  if (!isOneOf(OUTCOMES, outcome)) return null
  const applied = outcome === "created" || outcome === "already_exists"
  if (applied !== isLabelReference(value["reference"])) return null
  const failed = outcome === "failed" || outcome === "unverified"
  return {
    name: value["name"],
    description: typeof value["description"] === "string" ? value["description"] : "",
    color: labelColor(value["background_color"]),
    outcome,
    details: failed
      ? typeof value["message"] === "string"
        ? value["message"]
        : "Google Ads didn't confirm this label."
      : "",
    errorCode: failed && typeof value["error_code"] === "string" ? value["error_code"] : "",
  }
}
