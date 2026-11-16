// apps/web/src/integrations/outlook_calendar/index.ts

import type { IntegrationUiModule } from "@/integrations/contract"
import { MicrosoftConnectHelp } from "@/integrations/microsoft-connect-help"
import { OutlookCalendarLogo } from "@/integrations/outlook_calendar/components/logo"
import { outlookCalendarAvailabilityPresenter } from "@/integrations/outlook_calendar/presenters/availability"
import { outlookCalendarCancelPresenter } from "@/integrations/outlook_calendar/presenters/cancel-event"
import { outlookCalendarCreateEventPresenter } from "@/integrations/outlook_calendar/presenters/create-event"
import {
  outlookCalendarListEventsPresenter,
  outlookCalendarReadEventPresenter,
} from "@/integrations/outlook_calendar/presenters/events"
import { outlookCalendarMeetingTimesPresenter } from "@/integrations/outlook_calendar/presenters/meeting-times"
import { outlookCalendarPeoplePresenter } from "@/integrations/outlook_calendar/presenters/people"
import { outlookCalendarRespondPresenter } from "@/integrations/outlook_calendar/presenters/respond-to-event"
import { outlookCalendarUpdateEventPresenter } from "@/integrations/outlook_calendar/presenters/update-event"

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
    outlookCalendarCreateEventPresenter,
    outlookCalendarUpdateEventPresenter,
    outlookCalendarRespondPresenter,
    outlookCalendarCancelPresenter,
  ],
} satisfies IntegrationUiModule
