// apps/web/src/integrations/ads/components/percent-input.tsx

import { CommittedInput } from "@/integrations/ads/components/committed-input"

/** A field that changes several amounts by one percentage, such as "10" or "-5%". */
export function PercentInput({
  disabled,
  label,
  onCommit,
}: {
  disabled: boolean
  label: string
  onCommit: (percent: number) => void
}) {
  return (
    <CommittedInput
      ariaLabel={label}
      className="h-7 w-28 text-sm tabular-nums"
      disabled={disabled}
      onCommit={(next) => {
        const percent = Number(next.trim().replace(/%$/, ""))
        if (next.trim() && Number.isFinite(percent) && percent > -100) onCommit(percent)
      }}
      placeholder="Change by %"
      value=""
    />
  )
}
