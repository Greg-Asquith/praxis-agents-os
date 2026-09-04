// apps/web/src/integrations/google_search_console/components/inspection-results.tsx

import { ChevronDownIcon, ExternalLinkIcon } from "lucide-react"

import { ExternalContent } from "@/components/tool-ui/external-content"
import { nodeText, type UntrustedNode } from "@/components/tool-ui/untrusted-node"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import type { SearchConsoleInspection } from "@/integrations/google_search_console/lib/inspection-model"
import { formatDateTime, pluralize, titleCaseToken } from "@/lib/format"

export function InspectionResults({ inspections }: { inspections: SearchConsoleInspection[] }) {
  if (inspections.length === 0) {
    return <p className="text-muted-foreground text-sm">No URL inspections were returned.</p>
  }
  return (
    <div className="grid gap-3">
      {inspections.map((inspection) => (
        <InspectionCard inspection={inspection} key={inspection.url} />
      ))}
    </div>
  )
}

function InspectionCard({ inspection }: { inspection: SearchConsoleInspection }) {
  return (
    <article className="border-border bg-muted/15 grid min-w-0 gap-3 rounded-lg border p-3">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs font-medium">Inspected URL</p>
          <p className="text-sm font-medium wrap-break-word">{inspection.url}</p>
        </div>
        {inspection.errorCode ? null : (
          <Badge variant={verdictVariant(inspection.verdict)}>
            {titleCaseToken(inspection.verdict, "Unknown verdict")}
          </Badge>
        )}
      </div>
      {inspection.errorCode && inspection.message ? (
        <ExternalContent
          label="URL inspection error"
          showSource={false}
          value={inspection.message}
        />
      ) : (
        <InspectionDetail inspection={inspection} />
      )}
    </article>
  )
}

function InspectionDetail({ inspection }: { inspection: SearchConsoleInspection }) {
  return (
    <>
      <dl className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
        <Detail label="Coverage" value={inspection.coverageState || "Not reported"} />
        <Detail
          label="Last crawl"
          value={
            inspection.lastCrawlTime ? formatDateTime(inspection.lastCrawlTime) : "Not reported"
          }
        />
        <Detail label="Crawled as" value={inspection.crawledAs || "Not reported"} />
        <Detail label="Page fetch" value={inspection.pageFetchState || "Not reported"} />
        <Detail label="Indexing" value={inspection.indexingState || "Not reported"} />
        <Detail label="Robots.txt" value={inspection.robotsTxtState || "Not reported"} />
      </dl>
      <dl className="border-border grid gap-2 border-t pt-3 text-xs sm:grid-cols-2">
        <ExternalDetail label="Google canonical" value={inspection.googleCanonical} />
        <ExternalDetail label="User canonical" value={inspection.userCanonical} />
      </dl>
      <div className="grid gap-2 sm:grid-cols-2">
        <UrlDisclosure label="Sitemaps" values={inspection.sitemap} />
        <UrlDisclosure label="Referring URLs" values={inspection.referringUrls} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">
          Mobile usability: {titleCaseToken(inspection.mobileUsabilityVerdict, "Not reported")}
        </Badge>
        <Badge variant="outline">
          Rich results: {titleCaseToken(inspection.richResultsVerdict, "Not reported")}
        </Badge>
        {inspection.richResults.map((result) => (
          <Badge key={result.type} variant={result.issueCount > 0 ? "warning" : "secondary"}>
            {result.type}: {result.issueCount.toLocaleString()}{" "}
            {pluralize(result.issueCount, "issue")}
          </Badge>
        ))}
      </div>
      {inspection.inspectionResultLink.startsWith("https://") ? (
        <div>
          <a
            className={buttonVariants({ variant: "outline", size: "sm" })}
            href={inspection.inspectionResultLink}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLinkIcon data-icon="inline-start" />
            Open in Search Console
          </a>
        </div>
      ) : null}
    </>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="wrap-break-word">{value}</dd>
    </div>
  )
}

function ExternalDetail({ label, value }: { label: string; value: UntrustedNode | null }) {
  return <Detail label={label} value={nodeText(value) ?? "Not reported"} />
}

function UrlDisclosure({ label, values }: { label: string; values: UntrustedNode[] }) {
  return (
    <details className="group min-w-0 rounded-md border">
      <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-3 py-2 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        <span>
          {label} <span className="text-muted-foreground">({values.length.toLocaleString()})</span>
        </span>
        <ChevronDownIcon className="text-muted-foreground size-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t p-3">
        {values.length > 0 ? (
          <ul className="grid gap-1.5">
            {values.map((value, index) => (
              <li
                className="bg-muted/30 rounded px-2 py-1 text-xs wrap-break-word"
                key={`${value.content}:${String(index)}`}
              >
                {nodeText(value)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-xs">None reported.</p>
        )}
      </div>
    </details>
  )
}

function verdictVariant(verdict: string): "success" | "destructive" | "secondary" {
  if (verdict.toUpperCase() === "PASS") return "success"
  if (verdict.toUpperCase() === "FAIL") return "destructive"
  return "secondary"
}
