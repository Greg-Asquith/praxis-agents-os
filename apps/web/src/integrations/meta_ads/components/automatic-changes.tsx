// apps/web/src/integrations/meta_ads/components/automatic-changes.tsx

import { ChevronRightIcon } from "lucide-react"
import { useId, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { SettingRow } from "@/integrations/meta_ads/components/setting-rows"
import {
  CHANGE_GROUP_TITLES,
  CHANGE_GROUPS,
  formatTag,
} from "@/integrations/meta_ads/lib/automatic-changes"
import type { CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { toggleChange } from "@/integrations/meta_ads/lib/create-ads-edits"
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
  const groups = CHANGE_GROUPS.map((group) => ({
    group,
    changes: args.catalogue.filter((change) => change.group === group),
  })).filter(({ changes }) => changes.length > 0)
  const [openGroup, setOpenGroup] = useState(
    () =>
      groups.find(({ changes }) => changes.some((change) => enabled.includes(change.key)))?.group
  )
  const labels = args.catalogue.filter((change) => enabled.includes(change.key)).map((c) => c.label)
  const summary =
    labels.length > 0
      ? `${String(labels.length)} of ${String(args.catalogue.length)} on: ${labels.join(", ")}`
      : "All off. Your ads run exactly as written."
  return (
    <SettingRow rowKey="advanced" summary={summary} title="Advanced Settings">
      <div className="@container grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm">
            Meta&apos;s changes to your ads. All off means your ads run exactly as written.
          </p>
          <Button
            disabled={disabled || enabled.length === 0}
            onClick={() => {
              onChange(null)
            }}
            type="button"
            variant="outline"
          >
            Turn All Off
          </Button>
        </div>
        <div className="divide-y overflow-hidden rounded-lg border">
          {groups.map(({ group, changes }) => {
            const on = changes.filter((change) => enabled.includes(change.key)).length
            const open = openGroup === group
            return (
              <div key={group} className={cn(open && "bg-background")}>
                <button
                  aria-controls={open ? `${id}-${group}` : undefined}
                  aria-expanded={open}
                  className="hover:bg-muted/60 focus-visible:ring-ring/50 flex min-h-10 w-full cursor-pointer items-center gap-2 px-3 py-2 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset"
                  onClick={() => {
                    setOpenGroup(open ? undefined : group)
                  }}
                  type="button"
                >
                  <ChevronRightIcon
                    aria-hidden="true"
                    className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")}
                  />
                  <span className="flex-1 text-sm font-medium">{CHANGE_GROUP_TITLES[group]}</span>
                  <span className={cn("text-sm", on > 0 ? "font-medium" : "text-muted-foreground")}>
                    {String(on)} of {String(changes.length)} on
                  </span>
                </button>
                {open ? (
                  <div
                    className="grid gap-x-6 gap-y-3 px-3 pt-1 pb-3 @xl:grid-cols-2"
                    id={`${id}-${group}`}
                  >
                    {changes.map((change) => {
                      const switchId = `${id}-${change.key}`
                      const tag = formatTag(change)
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
                            <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                              {change.label}
                              {change.aiGenerated ? <Badge variant="outline">AI</Badge> : null}
                              {tag ? <Badge variant="secondary">{tag}</Badge> : null}
                            </span>
                            <span className="text-muted-foreground text-sm">
                              {change.description}
                            </span>
                          </label>
                        </div>
                      )
                    })}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </SettingRow>
  )
}
