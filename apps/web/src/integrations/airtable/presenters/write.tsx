// apps/web/src/integrations/airtable/presenters/write.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { microLabelClass } from "@/components/ui/stat"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { AirtableLogo } from "@/integrations/airtable/components/logo"
import { isAirtableJson } from "@/integrations/airtable/lib/record-data"
import { AirtableFieldGrid } from "@/integrations/airtable/components/record-fields"
import { airtableRecordDetails } from "@/integrations/airtable/lib/tool-details"
import { AirtableToolHeading } from "@/integrations/airtable/components/tool-heading"
import {
  AirtableWriteFailure,
  AirtableWriteReceipt,
} from "@/integrations/airtable/components/write-outcome"
import { isRecord } from "@/lib/guards"

export const airtableCreateRecordPresenter = airtableWritePresenter({
  action: "create",
  approveLabel: "Approve & Create",
  completedHeading: "Create Airtable Record",
  key: "airtable-create-record",
  name: "airtable_create_record",
})

export const airtableUpdateRecordPresenter = airtableWritePresenter({
  action: "update",
  approveLabel: "Approve & Update",
  completedHeading: "Update Airtable Record",
  key: "airtable-update-record",
  name: "airtable_update_record",
})

type AirtableWriteConfig = {
  action: "create" | "update"
  approveLabel: string
  completedHeading: string
  key: string
  name: string
}

function airtableWritePresenter(config: AirtableWriteConfig): ToolRowPresenter {
  return {
    handlesApprovals: true,
    key: config.key,
    matches: (activity) => activity.name === config.name,
    render: ({ activity, approvalDecision, defaultOpen, ui }) => {
      const args = airtableWriteArgs(activity.args, config.action)
      if (approvalDecision) {
        if (!args) {
          return null
        }
        const fields = ui?.arg_fields ?? []
        return (
          <ToolApprovalDecisionCard
            activityId={activity.id}
            approveLabel={config.approveLabel}
            args={activity.args}
            controls={approvalDecision}
            fallbackFields={approvalFallbackFields(activity.args, fields)}
            fields={fields}
            icon={<AirtableLogo className="size-4" />}
            label={config.completedHeading}
            prompt={`The agent wants to ${config.action} this record in the selected Airtable bases.`}
            title={`Review Airtable record ${config.action}`}
            toolName={activity.name}
          >
            <div className="grid min-w-0 gap-1">
              <p className={microLabelClass}>Fields to write</p>
              <AirtableFieldGrid fields={args.fields} />
            </div>
          </ToolApprovalDecisionCard>
        )
      }
      if (activity.status === "running") {
        return writeSkeleton(config, `Creating Airtable record…`, `Updating Airtable record…`)
      }
      if (activity.status === "awaiting_approval") {
        return writeSkeleton(
          config,
          "Waiting for record creation approval…",
          "Waiting for record update approval…"
        )
      }
      if (activity.status === "denied") {
        return writeFailure(
          activity,
          config,
          `This record ${config.action} was declined. Nothing was changed.`,
          defaultOpen
        )
      }
      if (activity.status === "failed" || activity.status === "unknown") {
        return writeFailure(
          activity,
          config,
          `The ${config.action} did not finish. No Airtable change was confirmed.`,
          defaultOpen
        )
      }
      const fanOut = parseFanOutData(activity.result, recordIdResult)
      if (!fanOut) {
        return writeFailure(
          activity,
          config,
          `Praxis could not confirm the Airtable record ${config.action}.`,
          defaultOpen
        )
      }
      return (
        <div aria-label={`Airtable record ${config.action} results`} className="w-full min-w-0">
          <FanOutShell
            contextLabel="Base"
            defaultOpen={defaultOpen}
            details={airtableRecordDetails(activity.args)}
            entries={fanOut.entries}
            emptyLabel={`No Airtable bases ${config.action === "create" ? "created" : "updated"} a record.`}
            externalLabel="Base ID"
            heading={<AirtableToolHeading>{config.completedHeading}</AirtableToolHeading>}
          >
            {(_entry, index) => {
              const recordId = fanOut.data[index]
              return recordId ? (
                <AirtableWriteReceipt action={config.action} recordId={recordId} />
              ) : null
            }}
          </FanOutShell>
        </div>
      )
    },
  }
}

function writeFailure(
  activity: ToolActivity,
  config: AirtableWriteConfig,
  description: string,
  defaultOpen: boolean
) {
  return (
    <div aria-label={`Unconfirmed Airtable record ${config.action}`} className="w-full min-w-0">
      <FanOutShell
        contextLabel="Base"
        defaultOpen={defaultOpen}
        details={airtableRecordDetails(activity.args)}
        entries={[
          {
            connectionId: activity.id,
            data: null,
            displayName: "Selected Airtable base",
            errorMessage: description,
            externalId: "Selected Airtable base",
            status: "failed",
          },
        ]}
        externalLabel="Base ID"
        heading={<AirtableToolHeading>{config.completedHeading}</AirtableToolHeading>}
        renderFailed={() => (
          <AirtableWriteFailure
            description={description}
            fields={
              (
                airtableWriteArgs(activity.args, "create") ??
                airtableWriteArgs(activity.args, "update")
              )?.fields ?? null
            }
          />
        )}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}

function writeSkeleton(config: AirtableWriteConfig, createLabel: string, updateLabel: string) {
  return (
    <FanOutSkeleton
      heading={<AirtableToolHeading>{config.completedHeading}</AirtableToolHeading>}
      label={config.action === "create" ? createLabel : updateLabel}
    />
  )
}

function airtableWriteArgs(value: unknown, action: AirtableWriteConfig["action"]) {
  if (
    !isRecord(value) ||
    typeof value["table"] !== "string" ||
    !isRecord(value["fields"]) ||
    Object.keys(value["fields"]).length === 0 ||
    !isAirtableJson(value["fields"]) ||
    (action === "update" && typeof value["record_id"] !== "string")
  ) {
    return null
  }
  return {
    fields: value["fields"],
    recordId: typeof value["record_id"] === "string" ? value["record_id"] : null,
    table: value["table"],
  }
}

function recordIdResult(value: unknown): string | null {
  return isRecord(value) && typeof value["record_id"] === "string" && value["record_id"].trim()
    ? value["record_id"]
    : null
}
