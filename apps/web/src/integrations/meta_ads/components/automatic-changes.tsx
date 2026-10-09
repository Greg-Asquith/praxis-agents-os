// apps/web/src/integrations/meta_ads/components/automatic-changes.tsx

import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import {
  CHANGE_GROUP_TITLES,
  CHANGE_GROUPS,
  hasAiGeneratedChange,
  unappliedFormatsNote,
  type AdFormat,
} from "@/integrations/meta_ads/lib/automatic-changes"
import type { CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { toggleChange } from "@/integrations/meta_ads/lib/create-ads-edits"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

/** Every advanced setting and AI enhancement Meta offers, off unless the operator turns it on here. */
export function AutomaticChanges({
  args,
  disabled,
  onChange,
}: {
  args: CreateAdsArgs
  disabled: boolean
  onChange: (value: EditedValue) => void
}) {
  const id = useId()
  const enabled = args.enabledChanges
  const [open, setOpen] = useState(enabled.length > 0)
  const used = new Set<AdFormat>(args.ads.map((ad) => ad.format))
  const groups = CHANGE_GROUPS.map((group) => ({
    group,
    changes: args.catalogue.filter((change) => change.group === group),
  }))
  const summary =
    enabled.length === 0
      ? "All off. Your ads run exactly as shown."
      : `${String(enabled.length)} ${pluralize(enabled.length, "setting")} on. Meta changes your ads where these apply.`
  return (
    <section aria-label="Advanced settings" className="@container grid min-w-0 gap-2 border-t pt-3">
      <button
        aria-controls={open ? `${id}-changes` : undefined}
        aria-expanded={open}
        className="group focus-visible:ring-ring/50 flex w-full cursor-pointer items-center justify-between gap-3 rounded-md text-left outline-none focus-visible:ring-3"
        onClick={() => {
          setOpen((value) => !value)
        }}
        type="button"
      >
        <span className="grid gap-0.5">
          <span className="text-sm font-medium group-hover:underline">Advanced Settings</span>
          <span className="text-muted-foreground text-xs font-normal whitespace-normal">
            {summary}
          </span>
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className={cn(
            "text-muted-foreground size-4 shrink-0 transition-transform",
            open && "rotate-180"
          )}
        />
      </button>
      {hasAiGeneratedChange(args.catalogue, enabled) ? (
        <p className="text-warning-foreground text-sm">
          An AI enhancement is on, so every ad is created paused. Meta asks for these ads to be
          previewed before they run.
        </p>
      ) : null}
      {open ? (
        <div className="grid gap-3" id={`${id}-changes`}>
          {groups.map(({ group, changes }) =>
            changes.length > 0 ? (
              <fieldset key={group} className="grid gap-x-6 gap-y-3 @xl:grid-cols-2">
                <legend className="text-muted-foreground mb-2 text-xs font-medium">
                  {CHANGE_GROUP_TITLES[group]}
                </legend>
                {changes.map((change) => {
                  const switchId = `${id}-${change.key}`
                  const note = unappliedFormatsNote(change, used)
                  return (
                    // The switch sits right beside its label, so the pairing reads at any width.
                    <div key={change.key} className="flex items-start gap-3">
                      <Switch
                        checked={enabled.includes(change.key)}
                        className="mt-0.5"
                        disabled={disabled}
                        id={switchId}
                        onCheckedChange={(checked) => {
                          onChange(toggleChange(args, change.key, checked))
                        }}
                      />
                      <label className="grid min-w-0 cursor-pointer gap-0.5" htmlFor={switchId}>
                        <span className="flex flex-wrap items-center gap-1.5 text-sm">
                          {change.label}
                          {change.aiGenerated ? (
                            <Badge variant="outline">AI-Generated</Badge>
                          ) : null}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {change.description}
                          {note ? ` ${note}` : ""}
                        </span>
                      </label>
                    </div>
                  )
                })}
              </fieldset>
            ) : null
          )}
        </div>
      ) : null}
    </section>
  )
}
