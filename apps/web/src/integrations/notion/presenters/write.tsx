// apps/web/src/integrations/notion/presenters/write.tsx

import { NotionWriteReceipt } from "@/integrations/notion/components/write-results"
import {
  parseNotionCreatePageArgs,
  parseNotionPageArgs,
  type NotionWriteArgs,
} from "@/integrations/notion/lib/write-args"
import {
  parseNotionWriteResult,
  type NotionWriteKind,
  type NotionWriteResult,
} from "@/integrations/notion/lib/write-results"
import { notionProvider } from "@/integrations/notion/provider"
import type { IntegrationWriteCopySpec } from "@/integrations/write-copy"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

const CHECK = "Check the page in Notion before taking further action."

export const notionWritePresenter = createIntegrationWritePresenter({
  key: "notion-writes",
  variants: {
    notion_create_page: notionWrite({
      copy: { check: CHECK, effect: "created", object: "page", verb: "Create" },
      kind: "create",
      parseArgs: parseNotionCreatePageArgs,
      prompt: "The agent wants to create this page in Notion.",
    }),
    notion_update_page_content: notionWrite({
      copy: { check: CHECK, effect: "updated", object: "page content", verb: "Update" },
      kind: "content",
      parseArgs: parseNotionPageArgs,
      prompt: "The agent wants to replace this text in Notion.",
    }),
    notion_update_page_properties: notionWrite({
      copy: { check: CHECK, effect: "updated", object: "page properties", verb: "Update" },
      kind: "properties",
      parseArgs: parseNotionPageArgs,
      prompt: "The agent wants to change these Notion page properties.",
    }),
  },
})

function notionWrite({
  copy,
  kind,
  parseArgs,
  prompt,
}: {
  copy: IntegrationWriteCopySpec
  kind: NotionWriteKind
  parseArgs: (value: unknown) => NotionWriteArgs | null
  prompt: string
}) {
  return defineIntegrationWriteVariant<NotionWriteArgs, NotionWriteResult>(notionProvider, {
    approval: { parseArgs, prompt },
    copy,
    details: (args) => (args ? [{ label: "Page", value: args.label }] : []),
    parseResult: (value) => parseNotionWriteResult(value, kind),
    renderOutcome: (result) => <NotionWriteReceipt kind={kind} result={result} />,
  })
}
