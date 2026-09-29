// apps/web/src/integrations/google_ads/components/label-chip.tsx

// The name always carries the meaning; the swatch is decorative.
export function GoogleAdsLabelChip({ name, color }: { name: string; color: string | null }) {
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium">
      <span
        aria-hidden="true"
        className="border-border size-2.5 shrink-0 rounded-full border"
        style={color ? { backgroundColor: color } : undefined}
      />
      <span className="truncate">{name}</span>
    </span>
  )
}
