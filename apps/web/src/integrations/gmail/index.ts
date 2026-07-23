// apps/web/src/integrations/gmail/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { GmailLogo } from "@/integrations/gmail/logo"
import { gmailReadPresenter } from "@/integrations/gmail/read-presenter"
import { gmailSearchPresenter } from "@/integrations/gmail/search-presenter"
import { gmailSendPresenter } from "@/integrations/gmail/send-presenter"

export default {
  catalogDescription: "Let agents read and manage your emails.",
  icons: { gmail: GmailLogo },
  providerKey: "gmail",
  toolRowPresenters: [gmailSearchPresenter, gmailReadPresenter, gmailSendPresenter],
} satisfies IntegrationUiModule
