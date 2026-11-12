// apps/web/src/integrations/google_ads/components/create-asset-groups-approval.tsx

import { PencilIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import type { DataColumn } from "@/components/ui/data-table"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import { AssetGroupsEditor } from "@/integrations/google_ads/components/asset-groups-editor"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { ProblemList } from "@/integrations/google_ads/components/new-ad-groups"
import { parseCampaign } from "@/integrations/google_ads/lib/create-ad-groups"
import {
  assetGroupChecks,
  assetGroupsNeedCheck,
  campaignCheck,
  canCheckAssetGroups,
  createAssetGroupRows,
  requestProblems,
  type CreateAssetGroupsArgs,
} from "@/integrations/google_ads/lib/create-asset-groups"
import {
  parseCancelledAssetGroups,
  serializeAssetGroups,
  type DraftAssetGroup,
} from "@/integrations/google_ads/lib/performance-max"

const TOOL_NAME = "google_ads_create_asset_groups"
const PARENT_COLUMNS: DataColumn[] = [
  { key: "assetGroups", kind: "number", label: "Asset Groups", width: 110 },
  { key: "problems", kind: "text", label: "Problems", width: 140 },
]

export function CreateAssetGroupsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: CreateAssetGroupsArgs
  // The request Google last answered for.
  checked: CreateAssetGroupsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = useMemo(() => createAssetGroupRows(args), [args])
  // Cancelled asset groups, so Restore puts them back with their edits.
  const cancelled = parseCancelledAssetGroups(controls.retained, args.assetGroups)
  const [changing, setChanging] = useState(false)

  const save = (groups: readonly DraftAssetGroup[]) => {
    onFieldEdit("asset_groups", serializeAssetGroups(groups))
  }
  const cancel = (indexes: ReadonlySet<number>) => {
    controls.onRetain?.(
      serializeAssetGroups([...cancelled, ...args.assetGroups.filter((_, at) => indexes.has(at))])
    )
    save(args.assetGroups.filter((_, at) => !indexes.has(at)))
  }
  const restore = () => {
    save([...args.assetGroups, ...cancelled])
    controls.onRetain?.([])
  }
  const wholeRequest = requestProblems(args)
  const problems = rows.filter((row) => row.problems.length > 0).length + wholeRequest.length
  const campaignCancelled = rows.length === 0 && cancelled.length > 0

  return (
    <div className="grid min-w-0 gap-3">
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
              values: { assetGroups: campaignCancelled ? cancelled.length : rows.length },
            },
          ]}
          selected={args.campaign.key}
        />
      </div>
      <ProblemList problems={wholeRequest} />
      {rows.length > 0 ? (
        <AssetGroupsEditor
          checks={assetGroupChecks(args)}
          disabled={disabled}
          onCancel={cancel}
          onSave={save}
          retail={campaignCheck(args)?.retail ?? false}
          rows={rows}
          toolName={TOOL_NAME}
        />
      ) : null}
      {/* At the end, beside the approve button that waits on it. */}
      {assetGroupsNeedCheck(args, checked) ? (
        <CheckChanges
          canCheck={canCheckAssetGroups(args)}
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
