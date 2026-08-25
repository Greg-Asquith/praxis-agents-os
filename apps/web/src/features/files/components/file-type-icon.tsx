// apps/web/src/features/files/components/file-type-icon.tsx

import type { SVGProps } from "react"

import {
  fileVisualType,
  type FileTypeSource,
  type FileVisualType,
} from "@/features/files/file-type"

const VISUAL_DETAILS: Readonly<Record<FileVisualType, { color: string; label: string }>> = {
  audio: { color: "#9d3e91", label: "AUD" },
  csv: { color: "#168779", label: "CSV" },
  generic: { color: "#64748b", label: "FILE" },
  html: { color: "#d65a31", label: "HTML" },
  image: { color: "#7857b8", label: "IMG" },
  json: { color: "#9a6b12", label: "JSON" },
  markdown: { color: "#5c60a8", label: "MD" },
  pdf: { color: "#d13c35", label: "PDF" },
  presentation: { color: "#c84b31", label: "PPT" },
  spreadsheet: { color: "#237447", label: "XLS" },
  text: { color: "#53667a", label: "TXT" },
  video: { color: "#287b91", label: "VID" },
  word: { color: "#2b579a", label: "DOC" },
}

export function FileTypeIcon({
  file,
  ...props
}: SVGProps<SVGSVGElement> & { file: FileTypeSource }) {
  const visualType = fileVisualType(file)
  const details = VISUAL_DETAILS[visualType]

  return (
    <svg
      aria-hidden="true"
      data-file-type={visualType}
      focusable="false"
      viewBox="0 0 28 32"
      {...props}
    >
      <path
        d="M4 1h13l7 7v21a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2Z"
        fill={details.color}
      />
      <path d="M17 1v6a2 2 0 0 0 2 2h5Z" fill="#fff" opacity=".34" />
      <path d="M7 13h14v11H7z" fill="#fff" opacity=".16" />
      <text
        fill="#fff"
        fontFamily="ui-sans-serif, system-ui, sans-serif"
        fontSize={details.label.length === 4 ? 5.5 : 6.5}
        fontWeight="800"
        letterSpacing=".15"
        textAnchor="middle"
        x="14"
        y="21"
      >
        {details.label}
      </text>
    </svg>
  )
}
