import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { PlatformDocumentActions } from "@/features/knowledge/components/platform-document-actions"
import { CopyDocumentButton } from "@/features/knowledge/components/copy-document-button"
import type { KbDocumentDetail } from "@/features/knowledge/types"

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }))

const document: KbDocumentDetail = {
  id: "platform-doc",
  scope: "platform",
  workspace_id: null,
  is_published: false,
  can_manage_platform: true,
  title: "Delivery policy",
  source_type: "manual",
  status: "ready",
  source_sync_status: null,
  source_synced_at: null,
  processing_error: null,
  processing_attempts: 1,
  is_private: false,
  chunk_count: 1,
  created_by_user_id: null,
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  concept_id: null,
  source_updated_at: null,
  summary: null,
  external_url: null,
  content_md: "Reviewed policy",
  meta: { ingestion_version: "version-one" },
}

function render(overrides: Partial<KbDocumentDetail> = {}) {
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: new QueryClient(),
      children: createElement(PlatformDocumentActions, { document: { ...document, ...overrides } }),
    })
  )
}

describe("platform publication controls", () => {
  it("offers publication and editing for a prepared unpublished entry", () => {
    const html = render()
    expect(html).toContain(">Publish</button>")
    expect(html).toContain(">Edit</button>")
    expect(html).toContain(">Reprocess</button>")
    expect(html).not.toContain('disabled=""')
  })

  it("requires withdrawal before editing published knowledge", () => {
    const html = render({ is_published: true })
    expect(html).toContain(">Withdraw</button>")
    expect(html).not.toContain(">Edit</button>")
    expect(html).not.toContain(">Reprocess</button>")
    expect(html).not.toContain(">Publish</button>")
  })

  it.each(["pending", "processing"] as const)(
    "allows cancellation of a %s attempt without publication",
    (status) => {
      const html = render({ status })
      expect(html).toContain(">Withdraw</button>")
      expect(html).not.toContain(">Publish</button>")
    }
  )

  it.each([{ meta: {} }, { content_md: null }, { status: "error" as const }])(
    "disables publication without reviewed ready content: %o",
    (overrides) => {
      expect(render(overrides)).toMatch(/<button[^>]*disabled=""[^>]*>Publish<\/button>/)
    }
  )

  it("does not allow copying missing content", () => {
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, {
        client: new QueryClient(),
        children: createElement(CopyDocumentButton, {
          document: { ...document, content_md: null },
        }),
      })
    )
    expect(html).toMatch(/<button[^>]*disabled=""/)
    expect(html).toContain("Make a workspace copy")
  })
})
