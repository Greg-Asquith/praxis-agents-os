// apps/web/src/integrations/sharepoint/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { SharePointLogo } from "@/integrations/sharepoint/components/logo"
import { sharePointListFolderPresenter } from "@/integrations/sharepoint/presenters/list-folder"
import { sharePointSearchFilesPresenter } from "@/integrations/sharepoint/presenters/search-files"

export default {
  catalogDescription: "Let agents find and read files in SharePoint and OneDrive.",
  ConnectHelp: MicrosoftConnectHelp,
  Logo: SharePointLogo,
  providerKey: "sharepoint",
  toolRowPresenters: [sharePointListFolderPresenter, sharePointSearchFilesPresenter],
} satisfies IntegrationUiModule
