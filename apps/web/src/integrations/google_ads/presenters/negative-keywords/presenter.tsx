// apps/web/src/integrations/google_ads/presenters/negative-keywords/presenter.tsx

import type { ReactNode } from "react"

import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"

type PresenterCopy = {
  approvalLabel: { add: string; remove: string }
  approvalPrompt: { add: string; remove: string }
  approvalTitle: { add: string; remove: string }
  deniedDescription: { add: string; remove: string }
  emptyLabel: string
  failedDescription: string
  heading: string
  progressLabel: { add: string; remove: string }
  resultAriaLabel: string
  unconfirmedAriaLabel: string
  waitingLabel: string
}

type NegativeKeywordPresenterConfig<Args, Summary, Result> = {
  copy: PresenterCopy
  key: string
  parseArgs: (value: unknown, removing: boolean) => Args | null
  parseResult: (value: unknown, removing: boolean) => Result | null
  renderApprovalSummary: (summary: Summary) => ReactNode
  renderOutcome: (result: Result, removing: boolean) => ReactNode
  summarize: (value: unknown, fallback: Args) => Summary
  toolNames: { add: string; remove: string }
}

export function createNegativeKeywordPresenter<Args, Summary, Result>(
  config: NegativeKeywordPresenterConfig<Args, Summary, Result>
) {
  const resultFailure =
    `The system couldn't verify the ${config.copy.heading.toLowerCase()} changes. ` +
    "Check the Google Ads platform before taking further action."
  const malformedDescription =
    `The system couldn't verify this account's ${config.copy.heading.toLowerCase()} outcomes. ` +
    "Check the Google Ads platform before taking further action."
  const unverifiedDescription =
    `The system couldn't verify whether Google Ads applied these ${config.copy.heading.toLowerCase()} changes. ` +
    "Check the Google Ads platform before taking further action."

  return createGoogleAdsWritePresenter({
    key: config.key,
    variants: {
      [config.toolNames.add]: defineGoogleAdsWriteVariant({
        approval: {
          approveLabel: "Approve & Add",
          label: config.copy.approvalLabel.add,
          parseArgs: (value) => config.parseArgs(value, false),
          prompt: config.copy.approvalPrompt.add,
          renderSummary: (value, fallback) =>
            config.renderApprovalSummary(config.summarize(value, fallback)),
          title: config.copy.approvalTitle.add,
        },
        deniedDescription: config.copy.deniedDescription.add,
        emptyLabel: config.copy.emptyLabel,
        failedDescription: config.copy.failedDescription,
        heading: config.copy.heading,
        malformedDescription,
        parseResult: (value) => config.parseResult(value, false),
        progressLabel: config.copy.progressLabel.add,
        renderOutcome: (result) => config.renderOutcome(result, false),
        resultAriaLabel: config.copy.resultAriaLabel,
        resultFailure,
        unconfirmedAriaLabel: config.copy.unconfirmedAriaLabel,
        unverifiedDescription,
        waitingLabel: config.copy.waitingLabel,
      }),
      [config.toolNames.remove]: defineGoogleAdsWriteVariant({
        approval: {
          approveLabel: "Approve & Remove",
          label: config.copy.approvalLabel.remove,
          parseArgs: (value) => config.parseArgs(value, true),
          prompt: config.copy.approvalPrompt.remove,
          renderSummary: (value, fallback) =>
            config.renderApprovalSummary(config.summarize(value, fallback)),
          title: config.copy.approvalTitle.remove,
        },
        deniedDescription: config.copy.deniedDescription.remove,
        emptyLabel: config.copy.emptyLabel,
        failedDescription: config.copy.failedDescription,
        heading: config.copy.heading,
        malformedDescription,
        parseResult: (value) => config.parseResult(value, true),
        progressLabel: config.copy.progressLabel.remove,
        renderOutcome: (result) => config.renderOutcome(result, true),
        resultAriaLabel: config.copy.resultAriaLabel,
        resultFailure,
        unconfirmedAriaLabel: config.copy.unconfirmedAriaLabel,
        unverifiedDescription,
        waitingLabel: config.copy.waitingLabel,
      }),
    },
  })
}
