// apps/web/src/integrations/google_ads/components/device-adjustments.tsx

import { XIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BidAdjustment } from "@/integrations/google_ads/components/bid-adjustment"
import {
  DEVICE_NAMES,
  deviceText,
  EXCLUDED,
  type Device,
  type DeviceLine,
  type DeviceTarget,
} from "@/integrations/google_ads/lib/update-targeting"

function nowText(line: DeviceLine): string {
  if (line.now === null) return "Now: differs by campaign"
  const text = deviceText({ bidAdjustment: line.now, excluded: false })
  return `Now: ${text.charAt(0).toUpperCase()}${text.slice(1)}`
}

/** One row per device, with its adjustment now and the adjustment or exclusion asked for. */
export function DeviceAdjustments({
  disabled,
  lines,
  onChange,
}: {
  disabled: boolean
  lines: readonly DeviceLine[]
  // Null leaves the device as it is.
  onChange: (device: Device, next: Omit<DeviceTarget, "device"> | null) => void
}) {
  return (
    <div className="divide-y">
      {lines.map((line) => {
        const name = DEVICE_NAMES[line.device]
        const asked = line.requested === "varies" ? null : line.requested
        const excluded = asked ? asked.excluded : line.now === EXCLUDED
        const bid = asked ? asked.bidAdjustment : line.now
        return (
          <div
            key={line.device}
            className="flex min-h-12 min-w-0 flex-wrap items-center gap-2.5 py-1 pr-1.5 pl-3"
          >
            <div className="grid min-w-32 flex-1 text-sm">
              <span className="font-medium">{name}</span>
              <span className="text-muted-foreground text-xs">
                {line.requested === "varies" ? "Changes differ by campaign" : nowText(line)}
              </span>
            </div>
            {line.requested === null ? (
              <Badge className="mr-1.5" variant="secondary">
                No Change
              </Badge>
            ) : (
              <Badge variant={excluded ? "destructive" : "success"}>
                {excluded ? "Excluding" : "Changing"}
              </Badge>
            )}
            <BidAdjustment
              disabled={disabled || excluded}
              label={`Bid adjustment for ${name}`}
              onChange={(bidAdjustment) => {
                onChange(line.device, { bidAdjustment: bidAdjustment ?? 0, excluded: false })
              }}
              value={excluded || bid === null || bid === 0 ? null : bid}
            />
            <Button
              aria-pressed={excluded}
              disabled={disabled}
              onClick={() => {
                onChange(line.device, { bidAdjustment: 0, excluded: !excluded })
              }}
              size="sm"
              title={excluded ? "Show ads on this device again" : "Stop ads showing on this device"}
              type="button"
              variant={excluded ? "secondary" : "outline"}
            >
              {excluded ? "Excluded" : "Exclude"}
            </Button>
            {line.requested === null ? (
              <span aria-hidden="true" className="size-11 shrink-0" />
            ) : (
              <Button
                aria-label={`Cancel the change to ${name}`}
                className="size-11 shrink-0"
                disabled={disabled}
                onClick={() => {
                  onChange(line.device, null)
                }}
                size="icon"
                title="Cancel This Change"
                type="button"
                variant="ghost"
              >
                <XIcon aria-hidden="true" />
              </Button>
            )}
          </div>
        )
      })}
    </div>
  )
}
