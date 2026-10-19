// apps/web/src/integrations/meta_ads/components/ad-schedule.tsx

import { PlusIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { ChoiceCards, SelectField } from "@/integrations/meta_ads/components/campaign-controls"
import {
  DAY_LABELS,
  formatAdSchedule,
  formatHour,
  MAX_SCHEDULE_WINDOWS,
  scheduleCovers,
  WEEK,
  WEEKDAY_EVENINGS,
  type AdSchedule,
  type ScheduleWindow,
} from "@/integrations/meta_ads/lib/ad-set-delivery"
import { cn } from "@/lib/utils"

const HOURS = Array.from({ length: 24 }, (_, hour) => hour)
const START_OPTIONS = HOURS.map((hour) => ({ value: String(hour), label: formatHour(hour) }))
const END_OPTIONS = HOURS.map((hour) => ({ value: String(hour + 1), label: formatHour(hour + 1) }))
const ZONE_OPTIONS = [
  { value: "viewer", label: "Each Viewer's Time Zone" },
  { value: "account", label: "Ad Account Time Zone" },
]
const MODES = [
  {
    value: "always",
    label: "All Day, Every Day",
    description: "Meta shows the ads whenever it finds results.",
  },
  {
    value: "schedule",
    label: "On a Schedule",
    description: "Only at the hours you choose. Needs a lifetime budget.",
  },
]
/** The hours the ads run, as a compact week with one cell per hour; null runs all the time. */
function WeekGrid({ schedule, title }: { schedule: AdSchedule | null; title: string }) {
  return (
    <div className="grid min-w-0 gap-1">
      <span className="text-muted-foreground text-xs font-medium">{title}</span>
      <div
        aria-label={`${title}: ${schedule ? formatAdSchedule(schedule) : "all day, every day"}`}
        className="grid gap-0.5"
        role="img"
      >
        {WEEK.map((day) => (
          <div key={day} className="flex items-center gap-2">
            <span className="text-muted-foreground w-8 text-xs">{DAY_LABELS[day]}</span>
            <div className="flex flex-1 gap-px">
              {HOURS.map((hour) => (
                <span
                  key={hour}
                  className={cn(
                    "h-2.5 flex-1 rounded-[2px]",
                    schedule === null || scheduleCovers(schedule, day, hour)
                      ? "bg-primary"
                      : "bg-muted"
                  )}
                />
              ))}
            </div>
          </div>
        ))}
        <div className="text-muted-foreground ml-10 flex justify-between text-xs">
          <span>00:00</span>
          <span>12:00</span>
          <span>24:00</span>
        </div>
      </div>
    </div>
  )
}

/** Chooses when the ads run and edits the time windows; All Day sends "remove". */
export function AdScheduleField({
  current,
  disabled,
  onChange,
  schedule,
}: {
  // The ad set's schedule now; null runs all day, every day.
  current: AdSchedule | null
  disabled: boolean
  onChange: (value: AdSchedule | "remove") => void
  schedule: AdSchedule | null
}) {
  const setWindow = (index: number, window: ScheduleWindow | null) => {
    if (schedule === null) return
    const windows = schedule.windows.flatMap((item, at) =>
      at !== index ? [item] : window ? [window] : []
    )
    onChange({ ...schedule, windows })
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChoiceCards
        ariaLabel="When the Ads Run"
        columns={2}
        disabled={disabled}
        onChange={(mode) => {
          onChange(mode === "schedule" ? (current ?? WEEKDAY_EVENINGS) : "remove")
        }}
        options={MODES}
        value={schedule ? "schedule" : "always"}
      />
      {schedule ? (
        <>
          <SelectField
            className="sm:max-w-64"
            disabled={disabled}
            label="Time Zone"
            onChange={(zone) => {
              onChange({ ...schedule, time_zone: zone === "account" ? "account" : "viewer" })
            }}
            options={ZONE_OPTIONS}
            value={schedule.time_zone}
          />
          <ol aria-label="Time Windows" className="bg-background divide-y rounded-lg border">
            {schedule.windows.map((window, index) => (
              <WindowRow
                // eslint-disable-next-line react-x/no-array-index-key -- Rows hold no state; a key from the window's values would remount the row, and lose focus, on each edit.
                key={index}
                disabled={disabled}
                number={index + 1}
                onChange={(next) => {
                  setWindow(index, next)
                }}
                removable={schedule.windows.length > 1}
                window={window}
              />
            ))}
          </ol>
          {schedule.windows.length < MAX_SCHEDULE_WINDOWS ? (
            <Button
              className="justify-self-start"
              disabled={disabled}
              onClick={() => {
                onChange({
                  ...schedule,
                  windows: [
                    ...schedule.windows,
                    { days: ["saturday", "sunday"], start_hour: 10, end_hour: 16 },
                  ],
                })
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              Add Time Window
            </Button>
          ) : null}
        </>
      ) : null}
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <WeekGrid schedule={current} title="Now" />
        <WeekGrid schedule={schedule} title="After" />
      </div>
    </div>
  )
}

function WindowRow({
  disabled,
  number,
  onChange,
  removable,
  window,
}: {
  disabled: boolean
  number: number
  onChange: (window: ScheduleWindow | null) => void
  removable: boolean
  window: ScheduleWindow
}) {
  const title = `Time Window ${String(number)}`
  return (
    <li className="grid min-w-0 gap-2 px-3 py-2.5">
      <div className="flex min-h-8 items-center justify-between gap-2">
        <span className="text-sm font-medium">{title}</span>
        {removable ? (
          <Button
            aria-label={`Remove ${title}`}
            className="h-8"
            disabled={disabled}
            onClick={() => {
              onChange(null)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <XIcon aria-hidden="true" />
            Remove
          </Button>
        ) : null}
      </div>
      <fieldset className="grid min-w-0 gap-1">
        <legend className="sr-only">Days for {title}</legend>
        <div className="flex flex-wrap gap-1.5">
          {WEEK.map((day) => (
            <label
              key={day}
              className="flex min-h-8 cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 text-sm"
            >
              <Checkbox
                checked={window.days.includes(day)}
                disabled={disabled}
                onCheckedChange={(checked) => {
                  onChange({
                    ...window,
                    days: checked
                      ? [...window.days, day]
                      : window.days.filter((item) => item !== day),
                  })
                }}
              />
              {DAY_LABELS[day]}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="grid gap-2 sm:grid-cols-2">
        <SelectField
          disabled={disabled}
          label="From"
          onChange={(hour) => {
            onChange({ ...window, start_hour: Number(hour) })
          }}
          options={START_OPTIONS}
          value={String(window.start_hour)}
        />
        <SelectField
          disabled={disabled}
          label="Until"
          onChange={(hour) => {
            onChange({ ...window, end_hour: Number(hour) })
          }}
          options={END_OPTIONS}
          value={String(window.end_hour)}
        />
      </div>
    </li>
  )
}
