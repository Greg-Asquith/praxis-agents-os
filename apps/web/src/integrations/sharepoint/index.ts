// apps/web/src/integrations/sharepoint/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { SharePointLogo } from "@/integrations/sharepoint/components/logo"
import { sharePointFindInFilePresenter } from "@/integrations/sharepoint/presenters/find-in-file"
import { sharePointListFolderPresenter } from "@/integrations/sharepoint/presenters/list-folder"
import { sharePointOpenLinkPresenter } from "@/integrations/sharepoint/presenters/open-link"
import { sharePointReadFilePresenter } from "@/integrations/sharepoint/presenters/read-file"
import { sharePointSearchFilesPresenter } from "@/integrations/sharepoint/presenters/search-files"
import { sharePointCreateFolderPresenter } from "@/integrations/sharepoint/presenters/create-folder"
import { sharePointWriteFilePresenter } from "@/integrations/sharepoint/presenters/write-file"
import { sharePointUpdateFilePresenter } from "@/integrations/sharepoint/presenters/update-file"

export default {
  catalogDescription: "Let agents find, read, and save files in SharePoint and OneDrive.",
  ConnectHelp: MicrosoftConnectHelp,
  Logo: SharePointLogo,
  providerKey: "sharepoint",
  toolRowPresenters: [
    sharePointListFolderPresenter,
    sharePointSearchFilesPresenter,
    sharePointReadFilePresenter,
    sharePointOpenLinkPresenter,
    sharePointFindInFilePresenter,
    sharePointCreateFolderPresenter,
    sharePointWriteFilePresenter,
    sharePointUpdateFilePresenter,
  ],
} satisfies IntegrationUiModule
