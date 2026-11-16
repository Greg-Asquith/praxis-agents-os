// apps/web/src/integrations/outlook_calendar/provider.ts

import { OutlookCalendarLogo } from "@/integrations/outlook_calendar/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

// Calendar identifiers are opaque Graph IDs, so cards show only the calendar name.
export const outlookCalendarProvider: IntegrationProviderUi = {
  contextLabel: "Calendar",
  externalLabel: null,
  fallbackDisplayName: "Selected calendar",
  Logo: OutlookCalendarLogo,
  name: "Outlook Calendar",
  providerKey: "outlook_calendar",
}
