// apps/web/src/integrations/google_ads/components/failure-targets.tsx

import { Badge } from "@/components/ui/badge"

export function GoogleAdsFailureTargets({
  description,
  targets,
}: {
  description: string
  targets: readonly string[]
}) {
  return (
    <div className="grid gap-2">
      <p className="text-destructive text-sm">{description}</p>
      {targets.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {Array.from(new Set(targets)).map((target) => (
            <Badge key={target} variant="secondary">
              {target}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}
