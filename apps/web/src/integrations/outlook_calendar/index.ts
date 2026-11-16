// apps/web/src/integrations/outlook_calendar/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { OutlookCalendarLogo } from "@/integrations/outlook_calendar/components/logo"
import { outlookCalendarAvailabilityPresenter } from "@/integrations/outlook_calendar/presenters/availability"
import {
  outlookCalendarListEventsPresenter,
  outlookCalendarReadEventPresenter,
} from "@/integrations/outlook_calendar/presenters/events"
import { outlookCalendarMeetingTimesPresenter } from "@/integrations/outlook_calendar/presenters/meeting-times"
import { outlookCalendarPeoplePresenter } from "@/integrations/outlook_calendar/presenters/people"

export default {
  catalogDescription: "Let agents read and manage your Outlook calendar.",
  ConnectHelp: MicrosoftConnectHelp,
  Logo: OutlookCalendarLogo,
  providerKey: "outlook_calendar",
  toolRowPresenters: [
    outlookCalendarListEventsPresenter,
    outlookCalendarReadEventPresenter,
    outlookCalendarAvailabilityPresenter,
    outlookCalendarMeetingTimesPresenter,
    outlookCalendarPeoplePresenter,
  ],
} satisfies IntegrationUiModule
