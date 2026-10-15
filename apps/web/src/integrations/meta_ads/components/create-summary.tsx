// apps/web/src/integrations/meta_ads/components/create-summary.tsx

import { CircleAlertIcon, CircleCheckIcon, CircleXIcon } from "lucide-react"

import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import type { CreatedObjectResult } from "@/integrations/meta_ads/lib/create-summary"
import { cn } from "@/lib/utils"

const OBJECTS = {
  campaign: {
    noun: "campaign",
    paused: "Next, ask the agent to create ad sets and ads in it, then turn it on.",
    active: "Next, ask the agent to create ad sets and ads in it. It spends once they are active.",
  },
  adset: {
    noun: "ad set",
    paused: "Next, ask the agent to create ads in it, then turn it on.",
    active: "Next, ask the agent to create ads in it. It spends once they are approved.",
  },
} as const

/** One created campaign or ad set as a single line, then what to do next. */
export function CreatedObjectOutcome({
  result,
  type,
}: {
  result: CreatedObjectResult
  type: keyof typeof OBJECTS
}) {
  const { noun, paused, active } = OBJECTS[type]
  const manager = result.id ? adsManagerObjectUrl(type, result.accountId, result.id) : null
  const link = manager ? (
    <a
      className="text-primary text-sm underline-offset-2 hover:underline"
      href={manager}
      rel="noreferrer"
      target="_blank"
    >
      Open in Ads Manager
    </a>
  ) : null
  if (result.outcome === "created") {
    const status =
      result.effectiveStatus === "PAUSED" ? ", paused" : result.effectiveStatus ? ", active" : ""
    return (
      <div className="grid min-w-0 gap-1.5">
        <p className="flex min-w-0 items-start gap-2 text-sm">
          <CircleCheckIcon aria-hidden="true" className="text-success mt-0.5 size-4 shrink-0" />
          <span className="min-w-0 wrap-anywhere">
            <span className="font-medium">{result.name}</span> was created{status}
          </span>
        </p>
        <p className="text-sm">
          {status === ", active" ? active : paused} {link}
        </p>
        {result.recovered ? (
          <p className="text-foreground/75 text-sm">
            Meta&apos;s reply was lost, so the {noun} was found by its name.
          </p>
        ) : null}
      </div>
    )
  }
  const failed = result.outcome === "failed"
  const Icon = failed ? CircleXIcon : CircleAlertIcon
  return (
    <div className="grid min-w-0 gap-1.5">
      <p
        className={cn(
          "flex min-w-0 items-start gap-2 text-sm",
          failed ? "text-destructive" : "text-warning-text"
        )}
      >
        <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span className="min-w-0 wrap-anywhere">
          <span className="font-medium">{result.name}</span>{" "}
          {failed
            ? "wasn't created."
            : "may not have been created. Check Ads Manager before creating it again."}
        </span>
      </p>
      {result.message || result.errorCode ? (
        <p className="text-foreground/75 text-sm wrap-anywhere">
          {result.message}
          {result.errorCode ? ` (Error code: ${result.errorCode})` : ""}
        </p>
      ) : null}
      {link ? <p className="text-sm">{link}</p> : null}
    </div>
  )
}
