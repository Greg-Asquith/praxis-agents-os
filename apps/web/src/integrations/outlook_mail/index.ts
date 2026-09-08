// apps/web/src/integrations/outlook_mail/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"
import { outlookMailAttachmentPresenter } from "@/integrations/outlook_mail/presenters/attachment"
import { outlookMailDraftPresenter } from "@/integrations/outlook_mail/presenters/create-draft"
import { outlookMailFoldersPresenter } from "@/integrations/outlook_mail/presenters/folders"
import { outlookMailForwardPresenter } from "@/integrations/outlook_mail/presenters/forward-message"
import { outlookMailMovePresenter } from "@/integrations/outlook_mail/presenters/move-message"
import { outlookMailPeoplePresenter } from "@/integrations/outlook_mail/presenters/people"
import { outlookMailReadPresenter } from "@/integrations/outlook_mail/presenters/read"
import { outlookMailReplyPresenter } from "@/integrations/outlook_mail/presenters/reply-to-message"
import { outlookMailSearchPresenter } from "@/integrations/outlook_mail/presenters/search"
import { outlookMailSendDraftPresenter } from "@/integrations/outlook_mail/presenters/send-draft"
import { outlookMailSendPresenter } from "@/integrations/outlook_mail/presenters/send-message"
import { outlookMailUpdatePresenter } from "@/integrations/outlook_mail/presenters/update-message"

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
    outlookMailSendPresenter,
    outlookMailSendDraftPresenter,
    outlookMailReplyPresenter,
    outlookMailForwardPresenter,
    outlookMailDraftPresenter,
    outlookMailMovePresenter,
    outlookMailUpdatePresenter,
  ],
} satisfies IntegrationUiModule
