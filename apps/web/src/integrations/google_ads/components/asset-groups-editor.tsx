// apps/web/src/integrations/google_ads/components/asset-groups-editor.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useId, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { FormField, TextField } from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { SettingLine, SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import { ImageTiles } from "@/integrations/google_ads/components/image-tiles"
import { TextAssetList } from "@/integrations/google_ads/components/text-asset-list"
import {
  audienceSignalId,
  audienceSignalName,
  blankAssetGroup,
  IMAGE_LIMITS,
  IMAGE_TYPE_LABELS,
  IMAGE_TYPES,
  imageCount,
  imageProblem,
  imageShapeFor,
  isBare,
  MAX_AUDIENCE_SIGNALS,
  parseAudienceSignal,
  TEXT_LIMITS,
  SEARCH_THEME_LIMITS,
  textLines,
  type AssetGroupRow,
  type DraftAssetGroup,
  type DraftAudienceSignal,
  type PerformanceMaxChecks,
  type TextKind,
  urlOptionsSummary,
} from "@/integrations/google_ads/lib/performance-max"
import {
  parametersProblem,
  parametersText,
  parseParametersText,
} from "@/integrations/google_ads/lib/setting-changes"
import { cn } from "@/lib/utils"

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Asset Group", width: 220 },
  { key: "headlines", kind: "text", label: "Headlines", width: 90 },
  { key: "longHeadlines", kind: "text", label: "Long Headlines", width: 110 },
  { key: "descriptions", kind: "text", label: "Descriptions", width: 100 },
  { key: "images", kind: "text", label: "Images", width: 70 },
  { key: "themes", kind: "number", label: "Themes", width: 70 },
]
// Only with two or more groups, since a Performance Max campaign needs one.
const CANCEL_COLUMN: DataColumn = { key: "cancel", kind: "text", label: "Cancel", width: 60 }

const TEXT_ITEMS: Record<TextKind, string> = {
  descriptions: "Description",
  headlines: "Headline",
  longHeadlines: "Long Headline",
}

const TEXT_TITLES: Record<TextKind, string> = {
  descriptions: "Descriptions",
  headlines: "Headlines",
  longHeadlines: "Long Headlines",
}

/** Performance Max asset groups: a table of counts against Google's minimums, and the open one. */
export function AssetGroupsEditor({
  checks,
  disabled,
  onCancel,
  onSave,
  retail,
  rows,
  toolName,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  onCancel: (indexes: ReadonlySet<number>) => void
  onSave: (groups: DraftAssetGroup[]) => void
  // True when a product feed fills groups that link no assets of their own.
  retail: boolean
  rows: readonly AssetGroupRow[]
  // The tool whose approval runs image and audience searches.
  toolName: string
}) {
  const [open, setOpen] = useState(() => rows.find((row) => row.problems.length > 0)?.index ?? 0)
  const openRow = rows[Math.min(open, rows.length - 1)]
  const groups = rows.map((row) => row.group)
  const blank = blankAssetGroup(groups)
  const edit = (index: number, patch: Partial<DraftAssetGroup>) => {
    onSave(groups.map((group, at) => (at === index ? { ...group, ...patch } : group)))
  }
  const tableRows = useMemo<DataRow[]>(
    () =>
      rows.map((row) => ({
        cancel: "",
        descriptions: "",
        headlines: "",
        images: "",
        key: String(row.index),
        longHeadlines: "",
        name: row.group.name,
        themes: textLines(row.group.searchThemes).length,
      })),
    [rows]
  )
  return (
    <>
      <DataTable
        columns={rows.length > 1 ? [...COLUMNS, CANCEL_COLUMN] : COLUMNS}
        exportFilename="google-ads-new-asset-groups.csv"
        onRowClick={(row) => {
          setOpen(Number(row["key"]))
        }}
        renderCell={(column, row) => {
          const groupRow = rows[Number(row["key"])]
          if (!groupRow) return null
          const { group } = groupRow
          const bare = retail && isBare(group)
          if (column.key === "name")
            return (
              <span className="grid min-w-0 gap-0.5 whitespace-normal">
                <CommittedInput
                  ariaLabel="Asset group name"
                  disabled={disabled}
                  onCommit={(name) => {
                    edit(groupRow.index, { name })
                  }}
                  value={group.name}
                />
                {groupRow.problems[0] ? (
                  <span className="text-destructive text-xs wrap-anywhere">
                    {groupRow.problems[0]}
                  </span>
                ) : bare ? (
                  <span className="text-muted-foreground text-xs">Assets from the feed</span>
                ) : null}
              </span>
            )
          if (
            column.key === "headlines" ||
            column.key === "longHeadlines" ||
            column.key === "descriptions"
          ) {
            const kind = column.key
            return (
              <AssetMinimum
                count={textLines(group[kind]).length}
                minimum={bare ? 0 : TEXT_LIMITS[kind].min}
              />
            )
          }
          if (column.key === "images")
            return (
              <AssetMinimum
                count={group.images.length}
                minimum={0}
                // A shape can be short while the total looks enough, such as two landscapes.
                short={!bare && imagesShort(group)}
              />
            )
          if (column.key === "cancel")
            return (
              <Button
                aria-label={`Cancel ${group.name}`}
                disabled={disabled}
                onClick={(event) => {
                  event.stopPropagation()
                  onCancel(new Set([groupRow.index]))
                  setOpen(0)
                }}
                size="icon-xs"
                title="Cancel This Change"
                type="button"
                variant="ghost"
              >
                <XIcon />
              </Button>
            )
          return null
        }}
        rowClassName={(row) =>
          Number(row["key"]) === openRow?.index
            ? "bg-muted/70 shadow-[inset_3px_0_0_var(--primary)]"
            : undefined
        }
        rowDetails={false}
        rowNoun={["asset group", "asset groups"]}
        rows={tableRows}
      />
      {openRow ? (
        <AssetGroupFields
          key={openRow.index}
          checks={checks}
          disabled={disabled}
          onEdit={(patch) => {
            edit(openRow.index, patch)
          }}
          retail={retail}
          row={openRow}
          toolName={toolName}
        />
      ) : null}
      {blank ? (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            onSave([...groups, blank])
            setOpen(rows.length)
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <PlusIcon />
          Add Asset Group
        </Button>
      ) : null}
    </>
  )
}

function imagesShort(group: DraftAssetGroup): boolean {
  return IMAGE_TYPES.some((type) => imageCount(group, type) < IMAGE_LIMITS[type].min)
}

/** A count that turns red while it's under Google's minimum. */
function AssetMinimum({
  count,
  minimum,
  short = count < minimum,
}: {
  count: number
  minimum: number
  short?: boolean
}) {
  return (
    <span className={cn("tabular-nums", short && "text-destructive font-medium")}>
      {count < minimum ? `${String(count)} of ${String(minimum)}` : String(count)}
    </span>
  )
}

function minimumSummary(count: number, min: number, max: number): string {
  return min > 0
    ? `${String(count)} of at least ${String(min)} · up to ${String(max)}`
    : `${String(count)} · up to ${String(max)}`
}

function AssetGroupFields({
  checks,
  disabled,
  onEdit,
  retail,
  row,
  toolName,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  onEdit: (patch: Partial<DraftAssetGroup>) => void
  retail: boolean
  row: AssetGroupRow
  toolName: string
}) {
  const urlId = useId()
  const { group } = row
  const bare = retail && isBare(group)
  return (
    <div className={cn("rounded-lg border", row.problems.length > 0 && "border-destructive/50")}>
      <SettingRows ariaLabel={`${group.name} settings`} bare>
        <SettingLine htmlFor={urlId} title="Final URL">
          <Input
            className="text-sm"
            disabled={disabled}
            id={urlId}
            onChange={(event) => {
              onEdit({ finalUrl: event.currentTarget.value })
            }}
            value={group.finalUrl}
          />
        </SettingLine>
        {(["headlines", "longHeadlines", "descriptions"] as const).map((kind) => {
          const { length, max, min } = TEXT_LIMITS[kind]
          const count = textLines(group[kind]).length
          const minimum = bare ? 0 : min
          return (
            <SettingRow
              key={kind}
              rowKey={kind}
              summary={minimumSummary(count, minimum, max)}
              title={TEXT_TITLES[kind]}
              tone={count < minimum || count > max ? "error" : "neutral"}
            >
              <TextAssetList
                assets={group[kind].map((text) => ({ pin: null, text }))}
                disabled={disabled}
                heading={false}
                limits={{ length, max, min: minimum }}
                noun={TEXT_ITEMS[kind]}
                onChange={(assets) => {
                  onEdit({ [kind]: assets.map((asset) => asset.text) })
                }}
              />
            </SettingRow>
          )
        })}
        <SettingRow
          rowKey="images"
          summary={imagesSummary(group)}
          title="Images"
          tone={
            (!bare && imagesShort(group)) ||
            group.images.some((image) => imageProblem(image, checks))
              ? "error"
              : "neutral"
          }
        >
          <ImageTiles
            addLabel="Add Image"
            checks={checks}
            disabled={disabled}
            fieldKey="asset_groups"
            images={group.images}
            onChange={(images) => {
              onEdit({ images })
            }}
            shapeFor={imageShapeFor}
            shapes={IMAGE_TYPES}
            toolName={toolName}
          />
        </SettingRow>
        {group.videos.length > 0 ? (
          <SettingRow
            rowKey="videos"
            summary={`${String(group.videos.length)} YouTube video${group.videos.length === 1 ? "" : "s"}`}
            title="Videos"
          >
            <ul className="grid gap-1">
              {group.videos.map((video, at) => (
                <li key={String(video["asset_id"])} className="flex items-center gap-2 text-sm">
                  <span className="min-w-0 flex-1 wrap-anywhere">
                    {typeof video["label"] === "string" ? video["label"] : "YouTube video"}
                  </span>
                  <Button
                    aria-label="Remove video"
                    disabled={disabled}
                    onClick={() => {
                      onEdit({ videos: group.videos.filter((_, index) => index !== at) })
                    }}
                    size="icon-xs"
                    type="button"
                    variant="ghost"
                  >
                    <XIcon />
                  </Button>
                </li>
              ))}
            </ul>
          </SettingRow>
        ) : null}
        <SettingRow
          rowKey="themes"
          summary={`${String(textLines(group.searchThemes).length)} themes · guide Google, don't limit reach`}
          title="Search Themes"
        >
          <TextAssetList
            assets={group.searchThemes.map((text) => ({ pin: null, text }))}
            disabled={disabled}
            heading={false}
            limits={SEARCH_THEME_LIMITS}
            noun="Search Theme"
            onChange={(assets) => {
              onEdit({ searchThemes: assets.map((asset) => asset.text) })
            }}
          />
        </SettingRow>
        <SettingRow
          rowKey="audiences"
          summary={audiencesSummary(group.audienceSignals.length)}
          title="Audience Signals"
          tone={
            group.audienceSignals.some((signal) =>
              checks?.unknownAudiences.has(audienceSignalId(signal))
            )
              ? "error"
              : "neutral"
          }
        >
          <AudienceSignals
            checks={checks}
            disabled={disabled}
            onChange={(audienceSignals) => {
              onEdit({ audienceSignals })
            }}
            signals={group.audienceSignals}
            toolName={toolName}
          />
        </SettingRow>
        <SettingRow
          rowKey="urlOptions"
          summary={urlOptionsSummary(group)}
          title="URL Options"
          tone={parametersProblem(group.customParameters) ? "error" : "neutral"}
        >
          <TextField
            disabled={disabled}
            label="Final URL Suffix"
            onChange={(finalUrlSuffix) => {
              onEdit({ finalUrlSuffix })
            }}
            placeholder="utm_source=google&utm_medium=cpc"
            value={group.finalUrlSuffix}
          />
          <TextField
            disabled={disabled}
            label="Tracking Template"
            onChange={(trackingTemplate) => {
              onEdit({ trackingTemplate })
            }}
            placeholder="{lpurl}?source=google"
            value={group.trackingTemplate}
          />
          <FormField label="Custom Parameters">
            {(id) => (
              <CommittedInput
                ariaLabel="Custom parameters"
                className="text-sm"
                disabled={disabled}
                id={id}
                onCommit={(next) => {
                  const customParameters = parseParametersText(next)
                  if (customParameters) onEdit({ customParameters })
                }}
                placeholder="key=value, key=value"
                value={parametersText(group.customParameters)}
              />
            )}
          </FormField>
        </SettingRow>
      </SettingRows>
      {row.problems.length > 1 ? (
        <ul className="text-destructive grid gap-0.5 border-t px-3 py-2 text-xs" role="alert">
          {row.problems.map((problem) => (
            <li key={problem} className="wrap-anywhere">
              {problem}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function audiencesSummary(count: number): string {
  if (count === 0) return "None · optional"
  return `${String(count)} audience${count === 1 ? "" : "s"} · guide Google, don't limit reach`
}

/** The audiences in a group's signal, and a search for more. */
function AudienceSignals({
  checks,
  disabled,
  onChange,
  signals,
  toolName,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  onChange: (signals: DraftAudienceSignal[]) => void
  signals: readonly DraftAudienceSignal[]
  toolName: string
}) {
  const [adding, setAdding] = useState(false)
  const taken = new Set(signals.map(audienceSignalId))
  return (
    <div className="grid min-w-0 gap-2">
      {signals.length > 0 ? (
        <ul className="grid gap-1">
          {signals.map((signal, at) => (
            <li key={audienceSignalId(signal)} className="flex items-center gap-2 text-sm">
              <span
                className={cn(
                  "min-w-0 flex-1 wrap-anywhere",
                  checks?.unknownAudiences.has(audienceSignalId(signal)) && "text-destructive"
                )}
              >
                {audienceSignalName(signal, checks)}
              </span>
              <Button
                aria-label={`Remove ${audienceSignalName(signal, checks)}`}
                disabled={disabled}
                onClick={() => {
                  onChange(signals.filter((_, index) => index !== at))
                }}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                <XIcon />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {adding ? (
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <EntitySearch
              disabled={disabled}
              entityKind="google_ads_audience"
              fieldKey="asset_groups"
              // A combined audience can't be part of a signal.
              isTaken={(choice) => {
                const signal = parseAudienceSignal(choice.value)
                return signal === null || taken.has(audienceSignalId(signal))
              }}
              label="Search for an audience"
              onChoose={(choice) => {
                const signal = parseAudienceSignal(choice.value)
                if (signal) onChange([...signals, signal])
                setAdding(false)
              }}
              placeholder="Search your lists, interests, and custom audiences"
              searchRequired
              toolName={toolName}
            />
          </div>
          <Button
            onClick={() => {
              setAdding(false)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            Cancel
          </Button>
        </div>
      ) : signals.length < MAX_AUDIENCE_SIGNALS ? (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            setAdding(true)
          }}
          size="sm"
          type="button"
          variant="ghost"
        >
          <PlusIcon />
          Add an Audience
        </Button>
      ) : null}
    </div>
  )
}

function imagesSummary(group: DraftAssetGroup): string {
  const parts = IMAGE_TYPES.map((type) => {
    const count = imageCount(group, type)
    return count > 0 ? `${String(count)} ${IMAGE_TYPE_LABELS[type].toLowerCase()}` : null
  }).filter(Boolean)
  const total = group.images.length
  return total === 0
    ? "No images"
    : `${String(total)} image${total === 1 ? "" : "s"} · ${parts.join(", ")}`
}
