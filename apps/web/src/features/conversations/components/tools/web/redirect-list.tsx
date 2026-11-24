// apps/web/src/features/conversations/components/tools/web/redirect-list.tsx

import { httpStatusText } from "@/features/conversations/components/tools/web/web-error-text"
import type { WebRedirect } from "@/features/conversations/components/tools/web/web-redirects"

export function RedirectList({ redirects }: { redirects: WebRedirect[] }) {
  if (redirects.length === 0) return null
  return (
    <ol aria-label="Redirects" className="text-muted-foreground grid gap-0.5 text-xs">
      {redirects.map((hop, index) => (
        <li className="break-all" key={`${String(index)}-${hop.location}`}>
          {httpStatusText(hop.status)} → {hop.location}
        </li>
      ))}
    </ol>
  )
}
