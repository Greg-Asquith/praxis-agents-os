// apps/web/src/integrations/bigquery/components/logo.tsx

import type { SVGProps } from "react"

export function BigQueryLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 32 32" {...props}>
      <path
        d="M5 8.5C5 5.5 9.9 3 16 3s11 2.5 11 5.5v15C27 26.5 22.1 29 16 29S5 26.5 5 23.5v-15Z"
        fill="#4285f4"
      />
      <path
        d="M27 8.5c0 3-4.9 5.5-11 5.5S5 11.5 5 8.5m22 7.5c0 3-4.9 5.5-11 5.5S5 19 5 16"
        fill="none"
        stroke="white"
        strokeOpacity=".78"
        strokeWidth="1.7"
      />
      <path
        d="m18.7 19.3 5.1 5.1m-3.2-7.9a4.3 4.3 0 1 1-8.6 0 4.3 4.3 0 0 1 8.6 0Z"
        fill="none"
        stroke="white"
        strokeLinecap="round"
        strokeWidth="2"
      />
    </svg>
  )
}
