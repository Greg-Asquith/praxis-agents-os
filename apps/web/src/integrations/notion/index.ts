// apps/web/src/integrations/notion/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { NotionConnectHelp } from "@/integrations/notion/components/connect-help"
import { NotionLogo } from "@/integrations/notion/components/logo"
import { notionQueryDataSourcePresenter } from "@/integrations/notion/presenters/query-data-source"
import { notionReadPagePresenter } from "@/integrations/notion/presenters/read-page"
import { notionSearchPagesPresenter } from "@/integrations/notion/presenters/search-pages"

export default {
  catalogDescription: "Connect a Notion workspace and choose which pages agents can access.",
  ConnectHelp: NotionConnectHelp,
  icons: { notion: NotionLogo },
  providerKey: "notion",
  toolRowPresenters: [
    notionSearchPagesPresenter,
    notionReadPagePresenter,
    notionQueryDataSourcePresenter,
  ],
} satisfies IntegrationUiModule
