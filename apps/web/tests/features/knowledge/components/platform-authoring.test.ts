import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { Dialog } from "@/components/ui/dialog"
import { AddDocumentMenu } from "@/features/knowledge/components/add-document-menu"
import { ManualDocumentForm } from "@/features/knowledge/components/manual-document-form"
import { DocumentUploadButton } from "@/features/knowledge/components/document-upload-button"

describe("platform Knowledge authoring", () => {
  it.each([ManualDocumentForm, DocumentUploadButton])(
    "shows draft review guidance without a privacy choice",
    (component) => {
      const html = renderToStaticMarkup(
        createElement(QueryClientProvider, {
          client: new QueryClient(),
          children: createElement(Dialog, {
            children: createElement(component, { platform: true, onSaved: vi.fn() }),
          }),
        })
      )
      expect(html).toContain("review and publish it to every workspace")
      expect(html).not.toContain("Only me")
      expect(html).not.toContain("Private")
    }
  )

  it("does not load integration catalogues for platform authoring", () => {
    const client = new QueryClient()
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, {
        client,
        children: createElement(AddDocumentMenu, { platform: true }),
      })
    )
    expect(html).toContain("Add Document")
    expect(client.getQueryCache().getAll()).toEqual([])
  })
})
