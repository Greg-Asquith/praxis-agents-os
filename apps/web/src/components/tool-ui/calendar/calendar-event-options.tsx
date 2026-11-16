// apps/web/src/components/tool-ui/calendar/calendar-event-options.tsx

import { fieldWellClass } from "@/components/tool-ui/field-styles"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

export type CalendarEventOptionKey = "allDay" | "online" | "showAs"

/** Edits an event's on/off settings and availability on one compact line. */
export function CalendarEventOptions({
  allDay,
  disabled,
  id,
  online,
  onChange,
  showAs,
  showAsOptions,
}: {
  allDay: boolean
  disabled: boolean
  id: string
  online: boolean
  onChange: (key: CalendarEventOptionKey, value: boolean | string) => void
  showAs: string
  showAsOptions: { label: string; value: string }[]
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
      <div className="flex items-center gap-2">
        <Checkbox
          checked={online}
          disabled={disabled}
          id={`${id}-online`}
          onCheckedChange={(checked) => {
            onChange("online", checked)
          }}
        />
        <Label htmlFor={`${id}-online`}>Teams Meeting</Label>
      </div>
      <div className="flex items-center gap-2">
        <Checkbox
          checked={allDay}
          disabled={disabled}
          id={`${id}-all-day`}
          onCheckedChange={(checked) => {
            onChange("allDay", checked)
          }}
        />
        <Label htmlFor={`${id}-all-day`}>All Day</Label>
      </div>
      <div className="flex items-center gap-2">
        <Label htmlFor={`${id}-show-as`}>Show As</Label>
        <Select<string>
          disabled={disabled}
          onValueChange={(value) => {
            if (value !== null) onChange("showAs", value)
          }}
          value={showAs}
        >
          <SelectTrigger className={cn(fieldWellClass, "h-8 w-44")} id={`${id}-show-as`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start">
            <SelectGroup>
              {showAsOptions.map((option) => (
                <SelectItem key={option.value} label={option.label} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}
