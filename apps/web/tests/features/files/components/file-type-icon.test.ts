import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { FileTypeIcon } from "@/features/files/components/file-type-icon"
import { fileVisualType } from "@/features/files/file-type"

describe("fileVisualType", () => {
  it.each([
    ["Quarterly report.docx", "word"],
    ["Forecast.xlsx", "spreadsheet"],
    ["Review.pptx", "presentation"],
    ["Brief.pdf", "pdf"],
    ["export.csv", "csv"],
  ] as const)("maps %s to the %s visual", (name, expected) => {
    expect(fileVisualType({ name })).toBe(expected)
  })

  it("prefers a known media type and ignores its charset", () => {
    expect(fileVisualType({ contentType: "text/markdown; charset=utf-8", name: "notes.txt" })).toBe(
      "markdown"
    )
  })

  it("uses the file category when no more specific metadata is available", () => {
    expect(fileVisualType({ category: "video" })).toBe("video")
  })
})

describe("FileTypeIcon", () => {
  it("renders a decorative SVG with its resolved type", () => {
    const html = renderToStaticMarkup(
      createElement(FileTypeIcon, {
        file: { contentType: "application/vnd.ms-powerpoint" },
      })
    )

    expect(html).toContain('data-file-type="presentation"')
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain("PPT")
  })
})
