// apps/web/src/integrations/airtable/components/logo.tsx

import type { SVGProps } from "react"

export function AirtableLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 48 40" focusable="false" {...props}>
      <path
        fill="#fcb400"
        d="M21.9.5 2.4 8.6c-1.1.5-1.1 2 0 2.5l19.6 7.8c1.3.5 2.7.5 4 0l19.6-7.8c1.1-.4 1.1-2 0-2.5L26.1.5a5.6 5.6 0 0 0-4.2 0Z"
      />
      <path
        fill="#18bfff"
        d="m26.8 22.2 17.4-6.8c.9-.4 1.9.3 1.9 1.3v15.7c0 .6-.4 1.1-.9 1.3l-17.4 6.7c-.9.4-1.9-.3-1.9-1.3V23.5c0-.6.3-1.1.9-1.3Z"
      />
      <path
        fill="#f82b60"
        d="M20.2 22.6 3.7 16c-.9-.4-1.9.3-1.9 1.3v14.2c0 .6.3 1.1.9 1.3l16.5 6.7c.9.4 1.9-.3 1.9-1.3V23.9c0-.6-.3-1.1-.9-1.3Z"
      />
    </svg>
  )
}
