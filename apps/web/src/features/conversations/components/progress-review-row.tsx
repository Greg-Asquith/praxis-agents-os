// apps/web/src/features/conversations/components/progress-review-row.tsx

import { ClipboardCheckIcon } from "lucide-react"

import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import type { ProgressReview } from "@/features/conversations/message-parts/types"

const OUTCOMES = {
  continue: { label: "Continued", variant: "success" },
  ask_person: { label: "Paused for You", variant: "warning" },
  steer: { label: "Steered", variant: "secondary" },
} as const

export function ProgressReviewRow({ review }: { review: ProgressReview }) {
  const outcome =
    review.verdict === "continue" || review.verdict === "ask_person"
      ? OUTCOMES[review.verdict]
      : OUTCOMES.steer

  return (
    <ToolResultCard
      ariaLabel={`Progress Check: ${outcome.label}`}
      details={[
        { label: "Check", value: String(review.reviewNumber) },
        ...(review.reason ? [{ label: "Reason", value: review.reason }] : []),
      ]}
      // Only a steer has more to show: the instruction the agent received.
      expandable={Boolean(review.steerText)}
      heading={<ToolHeading icon={ClipboardCheckIcon}>Progress Check</ToolHeading>}
      summary={review.reason}
      trailing={<Badge variant={outcome.variant}>{outcome.label}</Badge>}
    >
      <figure className="grid min-w-0 gap-1.5">
        <figcaption className="text-muted-foreground text-xs">Sent to the Agent</figcaption>
        <blockquote className="border-border text-foreground/90 border-l-2 pl-3 text-sm leading-relaxed">
          {review.steerText}
        </blockquote>
      </figure>
    </ToolResultCard>
  )
}
