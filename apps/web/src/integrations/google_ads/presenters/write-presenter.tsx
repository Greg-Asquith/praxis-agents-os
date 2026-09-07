// apps/web/src/integrations/google_ads/presenters/write-presenter.tsx

import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
  type IntegrationWriteProvider,
  type IntegrationWriteRenderer,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { formatGoogleAdsAccountId } from "@/lib/format"

const provider: IntegrationWriteProvider = {
  contextLabel: "Account",
  externalLabel: "Customer ID",
  fallbackDisplayName: "Selected Google Ads account",
  formatContextValue: formatGoogleAdsAccountId,
  providerKey: "google_ads",
  renderHeading: (heading) => <GoogleAdsToolHeading>{heading}</GoogleAdsToolHeading>,
  renderIcon: () => <GoogleAdsLogo className="size-4" />,
}

export type GoogleAdsWriteVariant<Args, Result> = IntegrationWriteVariant<Args, Result>
export type GoogleAdsWriteRenderer = IntegrationWriteRenderer

export function defineGoogleAdsWriteVariant<Args, Result>(
  variant: GoogleAdsWriteVariant<Args, Result>
): GoogleAdsWriteRenderer {
  return defineIntegrationWriteVariant(provider, variant)
}

export const createGoogleAdsWritePresenter = createIntegrationWritePresenter
