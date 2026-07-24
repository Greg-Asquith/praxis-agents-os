// apps/web/src/integrations/gmail/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { GmailLogo } from "@/integrations/gmail/components/logo"
import { gmailReadPresenter } from "@/integrations/gmail/presenters/read"
import { gmailSearchPresenter } from "@/integrations/gmail/presenters/search"
import { gmailSendPresenter } from "@/integrations/gmail/presenters/send"

export default {
  catalogDescription: "Let agents read and manage your emails.",
  icons: { gmail: GmailLogo },
  providerKey: "gmail",
  toolRowPresenters: [gmailSearchPresenter, gmailReadPresenter, gmailSendPresenter],
} satisfies IntegrationUiModule
