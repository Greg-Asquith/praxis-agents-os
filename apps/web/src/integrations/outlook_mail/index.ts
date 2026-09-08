// apps/web/src/integrations/outlook_mail/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"
import { outlookMailAttachmentPresenter } from "@/integrations/outlook_mail/presenters/attachment"
import { outlookMailFoldersPresenter } from "@/integrations/outlook_mail/presenters/folders"
import { outlookMailPeoplePresenter } from "@/integrations/outlook_mail/presenters/people"
import { outlookMailReadPresenter } from "@/integrations/outlook_mail/presenters/read"
import { outlookMailSearchPresenter } from "@/integrations/outlook_mail/presenters/search"

export default {
  catalogDescription: "Let agents read and manage your Outlook email.",
  ConnectHelp: MicrosoftConnectHelp,
  icons: { outlook_mail: OutlookMailLogo },
  providerKey: "outlook_mail",
  toolRowPresenters: [
    outlookMailSearchPresenter,
    outlookMailReadPresenter,
    outlookMailFoldersPresenter,
    outlookMailPeoplePresenter,
    outlookMailAttachmentPresenter,
  ],
} satisfies IntegrationUiModule
