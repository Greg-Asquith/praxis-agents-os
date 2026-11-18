// apps/web/tests/features/email-suppressions/components/email-suppressions-table.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { EmailSuppressionsTable } from "@/features/email-suppressions/components/email-suppressions-table"
import type { EmailSuppression } from "@/features/email-suppressions/types"

const entries: EmailSuppression[] = [
  {
    created_at: "2026-11-18T09:00:00Z",
    created_by_name: null,
    created_by_user_id: null,
    email: "dana@example.com",
    id: "suppression-1",
    reason: "Asked not to be contacted",
    source: "manual",
  },
]

describe("EmailSuppressionsTable", () => {
  it("offers removal only to people who can remove", () => {
    const editor = renderToStaticMarkup(
      createElement(EmailSuppressionsTable, { entries, onRemove: null })
    )
    const manager = renderToStaticMarkup(
      createElement(EmailSuppressionsTable, { entries, onRemove: () => undefined })
    )
    expect(editor).toContain("dana@example.com")
    expect(editor).not.toContain("Remove dana@example.com")
    expect(manager).toContain("Remove dana@example.com")
  })
})
