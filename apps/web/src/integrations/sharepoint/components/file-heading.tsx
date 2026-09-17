// apps/web/src/integrations/sharepoint/components/file-heading.tsx

import type { ReactNode } from "react"

export function SharePointFileHeading({
  name,
  webUrl,
  children,
}: {
  name: string
  webUrl: string | null
  children?: ReactNode
}) {
  return (
    <div className="min-w-0 flex-1">
      <p className="text-sm font-medium wrap-break-word">{name}</p>
      {children}
      {webUrl ? (
        <a
          className="text-link hover:text-primary text-xs underline underline-offset-2"
          href={webUrl}
          rel="noopener noreferrer"
          target="_blank"
        >
          Open in SharePoint
        </a>
      ) : null}
    </div>
  )
}
