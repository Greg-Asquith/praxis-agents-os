// apps/web/src/integrations/notion/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { NotionConnectHelp } from "@/integrations/notion/components/connect-help"
import { NotionLogo } from "@/integrations/notion/components/logo"
import { notionQueryDataSourcePresenter } from "@/integrations/notion/presenters/query-data-source"
import { notionReadPagePresenter } from "@/integrations/notion/presenters/read-page"
import { notionSearchPagesPresenter } from "@/integrations/notion/presenters/search-pages"
import { notionWritePresenter } from "@/integrations/notion/presenters/write"

export default {
  catalogDescription: "Let agents read and update the Notion pages you choose.",
  ConnectHelp: NotionConnectHelp,
  Logo: NotionLogo,
  providerKey: "notion",
  toolRowPresenters: [
    notionSearchPagesPresenter,
    notionReadPagePresenter,
    notionQueryDataSourcePresenter,
    notionWritePresenter,
  ],
} satisfies IntegrationUiModule
