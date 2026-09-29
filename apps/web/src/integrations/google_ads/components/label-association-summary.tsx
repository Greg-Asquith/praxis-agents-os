// apps/web/src/integrations/google_ads/components/label-association-summary.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityGroup } from "@/integrations/google_ads/components/entity-card"
import { GoogleAdsLabelChip } from "@/integrations/google_ads/components/label-chip"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  LABEL_TARGET_KIND_LABELS,
  LABEL_TARGET_KINDS,
  type LabelAssociationArgs,
} from "@/integrations/google_ads/lib/labels"

export function GoogleAdsLabelAssociationSummary({ args }: { args: LabelAssociationArgs }) {
  const pairs = args.labels.length * args.targets.length
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Proposed label changes"
      countLine={`${approvalCountLine(pairs, "change")}: ${approvalCountLine(args.labels.length, "label")} × ${approvalCountLine(args.targets.length, "item")}`}
    >
      <div className="flex flex-wrap gap-1">
        {args.labels.map((label) => (
          <GoogleAdsLabelChip key={label.labelId} name={label.name} color={label.color} />
        ))}
      </div>
      {LABEL_TARGET_KINDS.map((kind) => {
        const targets = args.targets.filter((target) => target.kind === kind)
        return targets.length ? (
          <GoogleAdsEntityGroup
            key={kind}
            title={LABEL_TARGET_KIND_LABELS[kind]}
            meta={approvalCountLine(targets.length, "item")}
          >
            <ul className="text-sm">
              {targets.map((target) => (
                <li key={target.id} className="wrap-anywhere">
                  {target.name}
                </li>
              ))}
            </ul>
          </GoogleAdsEntityGroup>
        ) : null
      })}
    </GoogleAdsApprovalSection>
  )
}
