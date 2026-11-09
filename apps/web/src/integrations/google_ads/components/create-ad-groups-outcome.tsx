// apps/web/src/integrations/google_ads/components/create-ad-groups-outcome.tsx

import { useMemo } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  BUILD_KIND_LABELS,
  createAdGroupsSummary,
  hasFailures,
  hasUnverified,
  nothingCreated,
  type BuildKindCount,
  type CreateAdGroupsResult,
} from "@/integrations/google_ads/lib/create-ad-groups-result"

const PROBLEM_COLUMNS: DataColumn[] = [
  { key: "item", kind: "text", label: "Item", width: 220 },
  { key: "kind", kind: "text", label: "Kind", width: 120 },
  { key: "message", kind: "text", label: "Google Says", width: 360 },
]

// Google creates the ad groups and ads as chosen; keywords always start enabled.
function kindStatus(kind: BuildKindCount, result: CreateAdGroupsResult): "Paused" | "Enabled" {
  const followsRequest = kind.kind === "ad_group" || kind.kind === "ad"
  return followsRequest && result.requestedStatus === "PAUSED" ? "Paused" : "Enabled"
}

/** One row per kind of object, or Google's reasons when nothing was created. */
export function CreateAdGroupsOutcome({ result }: { result: CreateAdGroupsResult }) {
  const columns = useMemo<DataColumn[]>(
    () => [
      { key: "kind", kind: "text", label: "Kind", width: 200 },
      { key: "created", kind: "number", label: "Created", width: 100 },
      ...(hasFailures(result)
        ? [{ key: "failed", kind: "number" as const, label: "Failed", width: 100 }]
        : []),
      ...(hasUnverified(result)
        ? [{ key: "unverified", kind: "number" as const, label: "Unconfirmed", width: 120 }]
        : []),
      { key: "status", kind: "text", label: "Status", width: 110 },
    ],
    [result]
  )
  const rows = useMemo(
    () =>
      result.kinds.map((kind) => ({
        created: kind.created,
        failed: kind.failed,
        key: kind.kind,
        kind: BUILD_KIND_LABELS[kind.kind].many,
        status: kindStatus(kind, result),
        unverified: kind.unverified,
      })),
    [result]
  )
  const problemRows = useMemo(
    () =>
      result.problems.map((problem, index) => ({
        item: problem.item,
        key: String(index),
        kind: BUILD_KIND_LABELS[problem.kind].one,
        message: problem.message,
      })),
    [result.problems]
  )
  if (nothingCreated(result)) {
    const [only] = result.problems
    return (
      <div className="grid gap-3">
        <p className="text-destructive text-sm wrap-anywhere">
          {result.problems.length === 1 && only
            ? only.message
            : "Google rejected the request, so nothing was created."}{" "}
          Fix this and ask the agent to try again.
        </p>
        {result.problems.length > 1 ? (
          <DataTable
            columns={PROBLEM_COLUMNS}
            exportFilename="google-ads-ad-group-problems.csv"
            pageSize={25}
            rowDetails={false}
            rowNoun={["problem", "problems"]}
            rows={problemRows}
          />
        ) : null}
      </div>
    )
  }
  return (
    <DataTable
      columns={columns}
      exportFilename="google-ads-created-ad-groups.csv"
      renderCell={(column, row) =>
        column.key === "status" && Number(row["created"]) > 0 ? (
          <Badge variant={row["status"] === "Paused" ? "warning" : "success"}>
            {String(row["status"])}
          </Badge>
        ) : null
      }
      rowDetails={false}
      rowNoun={["kind", "kinds"]}
      rows={rows}
      summary={<span>{createAdGroupsSummary(result)}</span>}
    />
  )
}
