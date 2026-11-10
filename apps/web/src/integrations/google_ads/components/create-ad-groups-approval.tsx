// apps/web/src/integrations/google_ads/components/create-ad-groups-approval.tsx

import { InfoIcon, PencilIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type { DataColumn } from "@/components/ui/data-table"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import {
  AdGroupSummary,
  NewAdGroups,
  ProblemList,
} from "@/integrations/google_ads/components/new-ad-groups"
import {
  adGroupRows,
  adGroupsNeedCheck,
  campaignCheck,
  canCheckAdGroups,
  createAdGroupsCounts,
  keywordMixLine,
  parseCampaign,
  parseCancelledAdGroups,
  requestProblems,
  serializeAdGroups,
  type CreateAdGroupsArgs,
  type DraftAdGroup,
} from "@/integrations/google_ads/lib/create-ad-groups"

const TOOL_NAME = "google_ads_create_ad_groups"
const PARENT_COLUMNS: DataColumn[] = [
  { key: "adGroups", kind: "number", label: "Ad Groups", width: 110 },
  { key: "problems", kind: "text", label: "Problems", width: 140 },
]

export function CreateAdGroupsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdGroupsArgs
  // The request Google last answered for.
  checked: CreateAdGroupsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = useMemo(() => adGroupRows(args), [args])
  const counts = createAdGroupsCounts(rows)
  // Cancelled ad groups, so Restore puts them back with their edits.
  const cancelled = parseCancelledAdGroups(controls.retained, args.adGroups)
  const [changing, setChanging] = useState(false)

  const save = (adGroups: readonly DraftAdGroup[]) => {
    onFieldEdit("ad_groups", serializeAdGroups(adGroups))
  }
  const cancel = (indexes: ReadonlySet<number>) => {
    controls.onRetain?.(
      serializeAdGroups([...cancelled, ...args.adGroups.filter((_, at) => indexes.has(at))])
    )
    save(args.adGroups.filter((_, at) => !indexes.has(at)))
  }
  const restore = () => {
    save([...args.adGroups, ...cancelled])
    controls.onRetain?.([])
  }
  const wholeRequest = requestProblems(args)
  const problems = counts.problems + wholeRequest.length
  const campaignCancelled = rows.length === 0 && cancelled.length > 0

  return (
    <div className="grid min-w-0 gap-3">
      <BiddingNote args={args} />
      <StatusChoice
        activeNote="Active, pending approval. Will go live once approved by Google."
        disabled={disabled}
        onChange={(status) => {
          onFieldEdit("status", status === "active" ? "ENABLED" : "PAUSED")
        }}
        pausedNote="Paused. Will not appear or spend until activated."
        value={args.status === "ENABLED" ? "active" : "paused"}
      />
      <div className="grid min-w-0 gap-1.5">
        {changing ? (
          <EntityPicker
            currentLabel={args.campaign.label}
            disabled={disabled}
            fieldKey="campaign"
            label="Campaign"
            onChoose={(reference) => {
              if (parseCampaign(reference)) onFieldEdit("campaign", reference)
              setChanging(false)
            }}
            toolName={TOOL_NAME}
          />
        ) : (
          <Button
            className="w-fit justify-self-end"
            disabled={disabled}
            onClick={() => {
              setChanging(true)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <PencilIcon aria-hidden="true" />
            Change Campaign
          </Button>
        )}
        {/* One campaign per request, so its row only summarises and cancels. */}
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Campaign"
          onCancel={() => {
            cancel(new Set(rows.map((row) => row.index)))
          }}
          onSelect={() => undefined}
          onUndo={restore}
          rowNoun={["campaign", "campaigns"]}
          rows={[
            {
              cancelled: campaignCancelled,
              key: args.campaign.key,
              name: campaignCheck(args)?.name ?? args.campaign.label,
              problems: campaignCancelled ? 0 : problems,
              values: {
                adGroups: campaignCancelled ? cancelled.length : counts.adGroups,
                problems: campaignCancelled
                  ? "Cancelled"
                  : problems > 0
                    ? `${String(problems)} to fix`
                    : "None",
              },
            },
          ]}
          selected={args.campaign.key}
        />
      </div>
      <ProblemList problems={wholeRequest} />
      {rows.length > 1 || cancelled.length > 0 ? (
        <AdGroupSummary
          cancelled={cancelled.length}
          counts={counts}
          detail={`in ${args.campaign.label}`}
          disabled={disabled}
          keywordMix={keywordMixLine(rows)}
          onCancelProblems={() => {
            cancel(new Set(rows.filter((row) => row.problems.length > 0).map((row) => row.index)))
          }}
          onRestore={restore}
        />
      ) : null}
      <NewAdGroups
        currency={[...args.accounts.values()][0]?.currencyCode ?? null}
        disabled={disabled}
        onCancel={cancel}
        onSave={save}
        rows={rows}
        rules={campaignCheck(args)}
      />
      {/* At the end, beside the approve button that waits on it. */}
      {adGroupsNeedCheck(args, checked) ? (
        <CheckChanges
          canCheck={canCheckAdGroups(args)}
          disabled={disabled}
          label={args.checks.unavailable ? "Check Again" : "Check Changes"}
          note="Google hasn't checked these changes yet."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

/** Says once what the campaign's bidding means for these ad groups, or that it's unchecked. */
function BiddingNote({ args }: { args: CreateAdGroupsArgs }) {
  if (args.checks.unavailable) return null
  const check = campaignCheck(args)
  if (check === null) {
    return (
      <Alert role="note">
        <InfoIcon aria-hidden="true" />
        <AlertTitle>{args.campaign.label} Hasn't Been Checked</AlertTitle>
        <AlertDescription>
          Check these changes to see the campaign's bidding and whether its ad group names are free.
        </AlertDescription>
      </Alert>
    )
  }
  if (check.strategyName === null) return null
  return (
    <Alert role="note">
      <InfoIcon aria-hidden="true" />
      <AlertTitle>Campaign Uses {check.strategyName}</AlertTitle>
      <AlertDescription>
        {check.acceptsCpcBid
          ? "Each ad group can have its own click bid, and keywords can override it."
          : "Google sets bids, so these ad groups don't need their own click bids."}
      </AlertDescription>
    </Alert>
  )
}
