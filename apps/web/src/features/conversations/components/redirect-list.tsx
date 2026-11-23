// apps/web/src/features/conversations/components/redirect-list.tsx

import type { WebRedirect } from "@/features/conversations/components/web-redirects"

export function RedirectList({ redirects }: { redirects: WebRedirect[] }) {
  if (redirects.length === 0) return null
  return (
    <ol aria-label="Redirects" className="text-muted-foreground grid gap-0.5 text-xs">
      {redirects.map((hop, index) => (
        <li className="break-all" key={`${String(index)}-${hop.location}`}>
          {hop.status} → {hop.location}
        </li>
      ))}
    </ol>
  )
}
