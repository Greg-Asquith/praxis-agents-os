// apps/web/src/integrations/notion/components/logo.tsx

import type { SVGProps } from "react"

export function NotionLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 32 32" {...props}>
      <rect x="3" y="3" width="26" height="26" rx="3" fill="currentColor" />
      <path d="M10 23V9h3.8l6.9 9.9V9H24v14h-3.6l-7.1-10.1V23H10Z" fill="var(--background)" />
    </svg>
  )
}
