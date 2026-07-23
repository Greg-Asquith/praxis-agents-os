// apps/web/src/components/tool-ui/source.tsx
import { ExternalLinkIcon, GlobeIcon } from "lucide-react"

export function SourceListRow({
  domain,
  snippet,
  title,
  url,
}: {
  domain: string
  snippet: string | null
  title: string
  url: string
}) {
  return (
    <article className="hover:bg-muted/25 w-full min-w-0 rounded-md border px-3 py-2.5 transition-colors">
      <div className="flex min-w-0 items-start gap-2.5">
        <div className="bg-muted text-muted-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md">
          <GlobeIcon className="size-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <a
            className="focus-visible:ring-ring/50 group/link block min-w-0 rounded-sm outline-none focus-visible:ring-3"
            href={url}
            rel="noreferrer"
            target="_blank"
          >
            <span className="flex min-w-0 items-start gap-2">
              <span className="text-link group-hover/link:text-primary min-w-0 flex-1 text-sm font-medium wrap-break-word underline-offset-2 group-hover/link:underline">
                {title}
              </span>
              <ExternalLinkIcon
                aria-hidden="true"
                className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
              />
            </span>
            <span className="text-muted-foreground mt-0.5 block truncate text-xs">{domain}</span>
          </a>
          {snippet ? (
            <p className="text-muted-foreground mt-1.5 line-clamp-3 text-xs leading-relaxed wrap-break-word">
              {snippet}
            </p>
          ) : null}
        </div>
      </div>
    </article>
  )
}
