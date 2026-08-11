import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import type { EditedRecords } from "@/components/tool-ui/edited-values"
import {
  addRecordRow,
  removeRecordRow,
  updateRecordCell,
} from "@/components/tool-ui/records-field-values"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolUi, ToolUiField } from "@/features/tools/types"
import type { ToolActivity } from "@/integrations/contract"
import googleAdsModule from "@/integrations/google_ads"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsCampaignLinksPresenter } from "@/integrations/google_ads/presenters/campaign-links"
import { googleAdsCampaignStatusPresenter } from "@/integrations/google_ads/presenters/campaign-status"
import { googleAdsNegativeKeywordListsPresenter } from "@/integrations/google_ads/presenters/negative-keyword-lists"
import {
  googleAdsAdGroupNegativeKeywordsPresenter,
  googleAdsCampaignNegativeKeywordsPresenter,
  googleAdsListNegativeKeywordsPresenter,
} from "@/integrations/google_ads/presenters/negative-keywords"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { integrationToolRowPresenters, loadIntegrationUiModules } from "@/integrations/registry"

describe("Google Ads tool presenters", () => {
  it("renders a compact, exportable report table with clean headers and raw values", () => {
    const html = render(
      googleAdsReportPresenter.render(
        props({
          id: "report-1",
          kind: "result",
          name: "google_ads_run_report",
          status: "completed",
          args: { query: "SELECT campaign.id, metrics.cost_micros FROM campaign" },
          result: {
            results: [
              entry({
                currency_code: "GBP",
                rows: [
                  {
                    campaign: {
                      id: "987654",
                      resource_name: "customers/1234567890/campaigns/987654",
                      status: "ENABLED",
                    },
                    metrics: {
                      costMicros: "1250000",
                      averageCpc: "73040000",
                      costPerConversion: "51050000",
                      conversionRate: "0.25",
                      ctr: "0.125",
                      clicks: "5",
                    },
                    segments: { date: "2026-07-23" },
                  },
                ],
                row_count: 1,
                truncated: true,
                truncation_note: "Report limited to 1 row.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Run Google Ads Report")
    expect(html).toContain("Customer ID")
    expect(html).toContain("123-456-7890")
    expect(html).toMatch(/£1\.25|GBP\s*1\.25/)
    expect(html).toContain("12.5%")
    expect(html).toContain("25%")
    expect(html).toContain("£73.04")
    expect(html).toContain("£51.05")
    expect(html).toContain(">Average CPC<")
    expect(html).toContain(">Cost Per Conversion<")
    expect(html).toContain("987654")
    expect(html).toContain(">Cost<")
    expect(html).toContain(">Resource Name<")
    expect(html).toContain(">CTR<")
    expect(html).toContain(">ID<")
    expect(html).not.toContain(">Metrics Cost Micros<")
    expect(html).not.toContain(">Campaign Resource Name<")
    expect(html).toContain("Report limited to 1 row.")
    expect(html).toContain("Download Report CSV")
    expect(html).toContain("Open row 1 details")
    expect(html).toContain("Total")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("renders repeated Google Ads fields without falling back to the generic tool row", () => {
    const html = render(
      googleAdsReportPresenter.render(
        props({
          id: "report-repeated-fields",
          kind: "result",
          name: "google_ads_run_report",
          status: "completed",
          result: {
            results: [
              entry({
                currency_code: "GBP",
                rows: [
                  {
                    adGroupAd: {
                      ad: {
                        finalUrls: ["https://example.com/one", "https://example.com/two"],
                        responsiveSearchAd: {
                          descriptions: [
                            { text: "First description" },
                            { text: "Second description" },
                          ],
                          headlines: [
                            { pinnedField: "HEADLINE_1", text: "Primary headline" },
                            { text: "Second headline" },
                          ],
                        },
                      },
                    },
                  },
                ],
                row_count: 1,
                truncated: false,
                truncation_note: null,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads report results"')
    expect(html).toContain(">Final URLs<")
    expect(html).toContain("https://example.com/one, https://example.com/two")
    expect(html).toContain("Primary headline · Second headline")
    expect(html).toContain("First description · Second description")
    expect(html).not.toContain("GAQL Query")
  })

  it("renders report and account loading states", () => {
    expect(
      render(
        googleAdsReportPresenter.render(
          props({
            id: "report-1",
            kind: "call",
            name: "google_ads_run_report",
            status: "running",
          })
        )
      )
    ).toContain("Running Google Ads report…")
    expect(
      render(
        googleAdsAccountsPresenter.render(
          props({
            id: "accounts-1",
            kind: "call",
            name: "google_ads_list_accounts",
            status: "running",
          })
        )
      )
    ).toContain("Loading Google Ads accounts…")
  })

  it("renders the account hierarchy with business ids and capability badges", () => {
    const html = render(
      googleAdsAccountsPresenter.render(
        props({
          id: "accounts-1",
          kind: "result",
          name: "google_ads_list_accounts",
          status: "completed",
          result: {
            results: [
              entry({
                accounts: [
                  {
                    customer_id: "1111111111",
                    display_name: "Agency manager",
                    parent_customer_id: null,
                    manager: true,
                    currency_code: "GBP",
                    status: "ENABLED",
                    writable: false,
                    enabled: true,
                  },
                  {
                    customer_id: "2222222222",
                    display_name: "Client account",
                    parent_customer_id: "1111111111",
                    manager: false,
                    currency_code: "GBP",
                    status: "PAUSED",
                    writable: true,
                    enabled: false,
                  },
                ],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Agency manager")
    expect(html).toContain("Client account")
    expect(html).toContain("Customer ID")
    expect(html).toContain("123-456-7890")
    expect(html).not.toContain("1234567890")
    expect(html).toContain("111-111-1111")
    expect(html).toContain("222-222-2222")
    expect(html).toContain("Manager")
    expect(html).toContain("Writable")
    expect(html).toContain("Read only")
    expect(html).toContain("Not selected")
  })

  it("uses the existing approval controls with an editable status and strong warning", () => {
    const controls = approvalControls()
    const declaredFields = [
      field("campaign_ids", "Declared Campaigns", "entity_list", false),
      {
        ...field("status", "Declared Status", "text", true),
        options: ["ENABLED", "PAUSED"],
      },
    ]
    const rendered = googleAdsCampaignStatusPresenter.render(
      props(
        {
          id: "campaign-1",
          kind: "approval",
          name: "google_ads_update_campaign_status",
          status: "awaiting_approval",
          args: {
            campaign_ids: [
              campaignReference("10", "Summer Sale"),
              campaignReference("20", "Brand Awareness"),
            ],
            status: "PAUSED",
          },
        },
        controls,
        toolUi(declaredFields)
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (
      isValidElement<{
        controls: unknown
        fields: { key: string; editable: boolean; options: string[] }[]
      }>(rendered)
    ) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
      expect(rendered.props.fields).toBe(declaredFields)
      expect(rendered.props.fields).toContainEqual(
        expect.objectContaining({
          key: "status",
          editable: true,
          options: ["ENABLED", "PAUSED"],
        })
      )
    }
    const html = render(rendered)
    expect(html).toContain("This changes live campaign delivery.")
    expect(html).toContain("Summer Sale")
    expect(html).toContain("Brand Awareness")
    expect(html).toContain("Approve &amp; Update")
  })

  it("declines to render the approval card for legacy raw campaign ids", () => {
    expect(
      googleAdsCampaignStatusPresenter.render(
        props(
          {
            id: "campaign-legacy",
            kind: "approval",
            name: "google_ads_update_campaign_status",
            status: "awaiting_approval",
            args: { campaign_ids: ["10", "20"], status: "PAUSED" },
          },
          approvalControls(),
          toolUi([])
        )
      )
    ).toBeNull()
  })

  it("renders mixed campaign outcomes with per-campaign status and inline errors", () => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props({
          id: "campaign-1",
          kind: "result",
          name: "google_ads_update_campaign_status",
          status: "completed",
          args: {
            campaign_ids: [
              campaignReference("10", "Summer Sale"),
              campaignReference("20", "Brand Awareness"),
            ],
            status: "PAUSED",
          },
          result: {
            results: [
              entry({
                resource_names: ["customers/1234567890/campaigns/10"],
                campaign_errors: [
                  {
                    campaign_id: "20",
                    message: "Campaign is removed.",
                    error_code: "CANNOT_MODIFY_REMOVED_CAMPAIGN",
                  },
                ],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Succeeded")
    expect(html).toContain("Failed")
    expect(html).toContain("10")
    expect(html).toContain("20")
    expect(html).toContain("Campaign is removed.")
    expect(html).toContain("Updated")
  })

  it("reviews the edited negative-list campaign selection in the approval card", () => {
    const controls = approvalControls()
    controls.decision.edits = {
      action: "UNLINK",
      campaign_ids: [campaignReference("20", "Brand Awareness")],
      negative_list: sharedSetReference("50", "Edited exclusions"),
    }
    const declaredFields = [
      field("negative_list", "Negative Keyword List", "entity", true),
      field("campaign_ids", "Campaigns", "entity_list", true),
      {
        ...field("action", "Action", "text", true),
        options: ["LINK", "UNLINK"],
      },
    ]
    const rendered = googleAdsCampaignLinksPresenter.render(
      props(
        {
          id: "campaign-links-approval",
          kind: "approval",
          name: "google_ads_link_negative_keyword_list",
          status: "awaiting_approval",
          args: {
            action: "LINK",
            campaign_ids: [
              campaignReference("10", "Summer Sale"),
              campaignReference("20", "Brand Awareness"),
            ],
            negative_list: sharedSetReference("50", "Brand Protection"),
          },
        },
        controls,
        toolUi(declaredFields)
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (isValidElement<{ controls: unknown; fields: ToolUiField[] }>(rendered)) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
      expect(rendered.props.fields).toBe(declaredFields)
    }
    const html = render(rendered)
    expect(html).toContain("Remove negative keyword list")
    expect(html).toContain("Edited exclusions")
    expect(html).toContain("1 campaign selected")
    expect(html).toContain("Approve &amp; Apply")
  })

  it("renders linked, already-linked, and failed campaigns per account", () => {
    const html = render(
      googleAdsCampaignLinksPresenter.render(
        props({
          id: "campaign-links-result",
          kind: "result",
          name: "google_ads_link_negative_keyword_list",
          status: "completed",
          args: {
            action: "LINK",
            campaign_ids: [
              campaignReference("10", "Summer Sale"),
              campaignReference("20", "Brand Awareness"),
              campaignReference("30", "Shopping"),
            ],
            negative_list: sharedSetReference("50", "Brand Protection"),
          },
          result: {
            results: [
              entry({
                resource_names: ["customers/1234567890/campaignSharedSets/10~50"],
                skipped_existing: ["20"],
                campaign_errors: [
                  {
                    campaign_id: "30",
                    message: "Campaign is removed.",
                    error_code: "CAMPAIGN_REMOVED",
                  },
                ],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads campaign list results"')
    expect(html).toContain("Brand Protection")
    expect(html).toContain("Summer Sale")
    expect(html).toContain("Linked")
    expect(html).toContain("Already linked")
    expect(html).toContain("Campaign is removed.")
    expect(html).toContain("30")
  })

  it("renders unlinked and not-linked campaign outcomes", () => {
    const html = render(
      googleAdsCampaignLinksPresenter.render(
        props({
          id: "campaign-unlinks-result",
          kind: "result",
          name: "google_ads_link_negative_keyword_list",
          status: "completed",
          args: {
            action: "UNLINK",
            campaign_ids: [campaignReference("10", "Summer Sale")],
            negative_list: sharedSetReference("50", "Brand Protection"),
          },
          result: {
            results: [
              entry({
                resource_names: [],
                not_found: ["10"],
                campaign_errors: [],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Unlinked")
    expect(html).toContain("Not linked")
    expect(html).toContain("10")
  })

  it("renders created, existing, and failed negative keyword lists per account", () => {
    const html = render(
      googleAdsNegativeKeywordListsPresenter.render(
        props({
          id: "negative-lists-1",
          kind: "result",
          name: "google_ads_create_negative_keyword_list",
          status: "completed",
          args: {
            names: ["New exclusions", "Existing exclusions", "Rejected exclusions"],
          },
          result: {
            results: [
              entry({
                created_names: ["New exclusions"],
                resource_names: ["customers/1234567890/sharedSets/10"],
                skipped_existing: ["Existing exclusions"],
                list_errors: [
                  {
                    name: "Rejected exclusions",
                    message: "This list name is not allowed.",
                    error_code: "INVALID_NAME",
                  },
                ],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads negative keyword list results"')
    expect(html).toContain("New exclusions")
    expect(html).toContain("Existing exclusions")
    expect(html).toContain("Rejected exclusions")
    expect(html).toContain("Already existed")
    expect(html).toContain("This list name is not allowed.")
    expect(html).toContain("Created")
    expect(html).toContain("Failed")
  })

  it("renders explicit created names instead of inferring them from tool arguments", () => {
    const html = render(
      googleAdsNegativeKeywordListsPresenter.render(
        props({
          id: "negative-lists-unicode",
          kind: "result",
          name: "google_ads_create_negative_keyword_list",
          status: "completed",
          args: { names: ["Straße", "STRASSE", "Other"] },
          result: {
            results: [
              entry({
                created_names: ["Straße", "Other"],
                resource_names: [
                  "customers/1234567890/sharedSets/10",
                  "customers/1234567890/sharedSets/11",
                ],
                skipped_existing: [],
                list_errors: [],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Straße")
    expect(html).toContain("Other")
    expect(html).not.toContain("STRASSE")
  })

  it("keeps negative keyword list approvals on the server-declared default card", () => {
    expect(googleAdsNegativeKeywordListsPresenter.handlesApprovals).toBeUndefined()
    expect(
      googleAdsNegativeKeywordListsPresenter.matches({
        id: "negative-lists-approval",
        kind: "approval",
        name: "google_ads_create_negative_keyword_list",
        status: "awaiting_approval",
        args: { names: ["New exclusions"] },
      })
    ).toBe(false)
  })

  it("renders an editable negative keyword approval with a match-type summary", () => {
    const controls = approvalControls()
    const declaredFields: ToolUiField[] = [
      {
        ...field("negative_list", "Negative Keyword List", "entity", true),
        entity_kind: "google_ads_shared_set",
      },
      {
        ...field("keywords", "Keywords", "records", true),
        columns: [
          { key: "text", label: "Keyword", options: [], placeholder: "" },
          {
            key: "match_type",
            label: "Match Type",
            options: ["EXACT", "PHRASE", "BROAD"],
            placeholder: "",
          },
        ],
      },
    ]
    const rendered = googleAdsListNegativeKeywordsPresenter.render(
      props(
        {
          id: "negative-keywords-approval",
          kind: "approval",
          name: "google_ads_add_negative_keywords",
          status: "awaiting_approval",
          args: {
            negative_list: sharedSetReference("50", "Brand Protection"),
            keywords: [
              { text: "free", match_type: "EXACT" },
              { text: "jobs", match_type: "PHRASE" },
              { text: "cheap", match_type: "BROAD" },
            ],
          },
        },
        controls,
        toolUi(declaredFields)
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (isValidElement<{ controls: unknown; fields: ToolUiField[] }>(rendered)) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
      expect(rendered.props.fields).toBe(declaredFields)
    }
    const html = render(rendered)
    expect(html).toContain("3 keywords")
    expect(html).toContain("Brand Protection")
    expect(html).toContain("Exact 1 · Phrase 1 · Broad 1")
    expect(html).toContain("Approve &amp; Add")
  })

  it("renders added, existing, and failed keyword rows per account", () => {
    const html = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props({
          id: "negative-keywords-result",
          kind: "result",
          name: "google_ads_add_negative_keywords",
          status: "completed",
          args: {
            negative_list: sharedSetReference("50", "Brand Protection"),
            keywords: [
              { text: "free", match_type: "EXACT" },
              { text: "jobs", match_type: "PHRASE" },
              { text: "cheap", match_type: "BROAD" },
            ],
          },
          result: {
            results: [
              entry({
                counts: { added: 1, skipped_existing: 1, failed: 1 },
                samples: {
                  added: [
                    {
                      text: "free",
                      match_type: "EXACT",
                      resource_name: "customers/1234567890/sharedCriteria/50~1",
                    },
                  ],
                  skipped_existing: [{ text: "jobs", match_type: "PHRASE" }],
                  failed: [
                    {
                      scope: "keyword",
                      text: "cheap",
                      match_type: "BROAD",
                      message: "Keyword is not permitted.",
                      error_code: "INVALID_KEYWORD_TEXT",
                    },
                  ],
                },
                samples_truncated: false,
                audit_note: "Full applied-change details are retained in the audit trail.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads negative keyword results"')
    expect(html).toContain("Added")
    expect(html).toContain("Already existed")
    expect(html).toContain("Failed")
    expect(html).toContain("free")
    expect(html).toContain("jobs")
    expect(html).toContain("cheap")
    expect(html).toContain("Keyword is not permitted.")
  })

  it("keeps valid keyword outcomes when a provider failure has no operation index", () => {
    const html = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props({
          id: "negative-keywords-unattributed-error",
          kind: "result",
          name: "google_ads_add_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { added: 401, skipped_existing: 73, failed: 26 },
                samples: {
                  added: [
                    {
                      text: "free",
                      match_type: "EXACT",
                      resource_name: "customers/1234567890/sharedCriteria/50~1",
                    },
                  ],
                  skipped_existing: [{ text: "jobs", match_type: "PHRASE" }],
                  failed: [
                    {
                      scope: "account",
                      message: "The account rejected part of the request.",
                      error_code: "INVALID_INPUT",
                    },
                  ],
                },
                samples_truncated: true,
                audit_note: "Full applied-change details are retained in the audit trail.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("free")
    expect(html).toContain("jobs")
    expect(html).toContain("Added")
    expect(html).toContain("Already existed")
    expect(html).toContain("Failed")
    expect(html).toContain("Account-level error")
    expect(html).toContain("The account rejected part of the request.")
    expect(html).toContain("401")
    expect(html).toContain("73")
    expect(html).toContain("26")
    expect(html).toContain("Showing representative rows")
  })

  it("updates the approval summary from edited keyword rows", () => {
    const controls = approvalControls()
    controls.decision.edits = {
      keywords: [
        { text: "one", match_type: "EXACT" },
        { text: "two", match_type: "EXACT" },
      ],
    }
    const html = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props(
          {
            id: "negative-keywords-edited",
            kind: "approval",
            name: "google_ads_add_negative_keywords",
            status: "awaiting_approval",
            args: {
              negative_list: sharedSetReference("50", "Brand Protection"),
              keywords: [{ text: "old", match_type: "BROAD" }],
            },
          },
          controls,
          toolUi([])
        )
      )
    )

    expect(html).toContain("2 keywords")
    expect(html).toContain("Exact 2 · Phrase 0 · Broad 0")
  })

  it("renders editable ANY removals and every settled removal outcome", () => {
    const controls = approvalControls()
    const approval = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props(
          {
            id: "negative-keywords-remove-approval",
            kind: "approval",
            name: "google_ads_remove_negative_keywords",
            status: "awaiting_approval",
            args: {
              negative_list: sharedSetReference("50", "Brand Protection"),
              keywords: [
                { text: "free", match_type: "ANY" },
                { text: "jobs", match_type: "PHRASE" },
              ],
            },
          },
          controls,
          toolUi([])
        )
      )
    )
    expect(approval).toContain("Approve &amp; Remove")
    expect(approval).toContain("Any 1")
    expect(approval).toContain("Removing them re-enables matching traffic")

    const settled = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props({
          id: "negative-keywords-remove-result",
          kind: "result",
          name: "google_ads_remove_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { removed: 2, not_found: 1, failed: 1 },
                samples: {
                  removed: [
                    {
                      text: "free",
                      match_type: "EXACT",
                      resource_name: "customers/123/sharedCriteria/50~1",
                    },
                    {
                      text: "free",
                      match_type: "BROAD",
                      resource_name: "customers/123/sharedCriteria/50~2",
                    },
                  ],
                  not_found: [{ text: "jobs", match_type: "ANY" }],
                  failed: [
                    {
                      scope: "keyword",
                      text: "cheap",
                      match_type: "PHRASE",
                      message: "Removal failed.",
                      error_code: "INVALID_INPUT",
                    },
                  ],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )
    expect(settled).toContain("Removed")
    expect(settled).toContain("Success")
    expect(settled).toContain("bg-success/10")
    expect(settled).toContain("Not found")
    expect(settled).toContain("free")
    expect(settled).toContain("jobs")
    expect(settled).toContain("cheap")
    expect(settled).toContain("Removal failed.")
    expect(settled).toContain("Invalid Input")
    expect(settled).toContain("Error Code")
  })

  it("derives the custom approval summary across incomplete keyword row states", () => {
    const controls = approvalControls()
    const activity: ToolActivity = {
      id: "negative-keywords-incomplete-edits",
      kind: "approval",
      name: "google_ads_add_negative_keywords",
      status: "awaiting_approval",
      args: {
        negative_list: sharedSetReference("50", "Brand Protection"),
        keywords: [{ text: "jobs", match_type: "EXACT" }],
      },
    }
    const columns = [
      { key: "text", label: "Keyword", options: [], placeholder: "" },
      {
        key: "match_type",
        label: "Match Type",
        options: ["EXACT", "PHRASE", "BROAD"],
        placeholder: "",
      },
    ]
    let rows: EditedRecords = [{ text: "jobs", match_type: "EXACT" }]

    assertCustomApproval(activity, controls, rows, "1 keyword", "Exact 1")

    rows = addRecordRow(rows, columns)
    assertCustomApproval(activity, controls, rows, "2 keywords", "Exact 1")

    rows = updateRecordCell(rows, 0, "text", "")
    assertCustomApproval(activity, controls, rows, "2 keywords", "Exact 1")

    rows = updateRecordCell(rows, 0, "text", "new jobs")
    rows = updateRecordCell(rows, 1, "match_type", "PHRASE")
    assertCustomApproval(activity, controls, rows, "2 keywords", "Phrase 1")

    rows = removeRecordRow(removeRecordRow(rows, 1), 0)
    assertCustomApproval(activity, controls, rows, "0 keywords", "Exact 0")

    rows = addRecordRow(rows, columns)
    rows = updateRecordCell(rows, 0, "text", "careers")
    rows = updateRecordCell(rows, 0, "match_type", "BROAD")
    assertCustomApproval(activity, controls, rows, "1 keyword", "Broad 1")
  })

  it("renders the campaign negative keyword approval fan-out summary", () => {
    const controls = approvalControls()
    const html = render(
      googleAdsCampaignNegativeKeywordsPresenter.render(
        props(
          {
            id: "campaign-negative-keywords-approval",
            kind: "approval",
            name: "google_ads_add_campaign_negative_keywords",
            status: "awaiting_approval",
            args: {
              campaign_ids: [
                campaignReference("10", "Brand"),
                campaignReference("20", "Prospecting"),
              ],
              keywords: [
                { text: "free", match_type: "EXACT" },
                { text: "jobs", match_type: "PHRASE" },
                { text: "cheap", match_type: "BROAD" },
              ],
            },
          },
          controls,
          toolUi([])
        )
      )
    )

    expect(html).toContain("3 keywords")
    expect(html).toContain("× 2 campaigns")
    expect(html).toContain("6 proposed changes")
    expect(html).toContain("blocking matching traffic")
    expect(html).toContain("Approve &amp; Add")
  })

  it("renders per-campaign negative keyword removal rollups and provider errors", () => {
    const html = render(
      googleAdsCampaignNegativeKeywordsPresenter.render(
        props({
          id: "campaign-negative-keywords-result",
          kind: "result",
          name: "google_ads_remove_campaign_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { removed: 3, not_found: 1, failed: 1 },
                campaigns: [
                  {
                    campaign_id: "10",
                    campaign_name: "Brand",
                    counts: { removed: 2, not_found: 0, failed: 0 },
                    campaign_errors: [],
                    errors_truncated: false,
                    keyword_outcomes: [
                      {
                        text: "free",
                        match_type: "EXACT",
                        outcome: "removed",
                        external_ref: "customers/111/campaignCriteria/10~1",
                      },
                      {
                        text: "jobs",
                        match_type: "PHRASE",
                        outcome: "removed",
                        external_ref: "customers/111/campaignCriteria/10~2",
                      },
                    ],
                  },
                  {
                    campaign_id: "20",
                    campaign_name: "Prospecting",
                    counts: { removed: 1, not_found: 1, failed: 1 },
                    campaign_errors: [
                      {
                        text: "cheap",
                        match_type: "BROAD",
                        message: "This campaign type rejected the criterion.",
                        error_code: "CANNOT_ADD_CRITERION",
                      },
                    ],
                    errors_truncated: false,
                    keyword_outcomes: [
                      {
                        text: "careers",
                        match_type: "EXACT",
                        outcome: "removed",
                        external_ref: "customers/111/campaignCriteria/20~3",
                      },
                      { text: "unavailable", match_type: "PHRASE", outcome: "not_found" },
                      {
                        text: "cheap",
                        match_type: "BROAD",
                        outcome: "failed",
                        error_code: "CANNOT_ADD_CRITERION",
                      },
                    ],
                  },
                ],
                campaigns_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads campaign negative keyword results"')
    expect(html).toContain("Brand")
    expect(html).toContain("Prospecting")
    expect(html).toContain("Removed")
    expect(html).toContain("Not found")
    expect(html).toContain("careers")
    expect(html).toContain("customers/111/campaignCriteria/20~3")
    expect(html).toContain("This campaign type rejected the criterion.")
  })

  it("renders ad group approval scope labels across campaigns", () => {
    const html = render(
      googleAdsAdGroupNegativeKeywordsPresenter.render(
        props(
          {
            id: "ad-group-negative-keywords-approval",
            kind: "approval",
            name: "google_ads_add_ad_group_negative_keywords",
            status: "awaiting_approval",
            args: {
              ad_group_ids: [
                adGroupReference("10", "Exact", "Brand"),
                adGroupReference("20", "Broad", "Prospecting"),
              ],
              keywords: [
                { text: "free", match_type: "EXACT" },
                { text: "jobs", match_type: "PHRASE" },
              ],
            },
          },
          approvalControls(),
          toolUi([])
        )
      )
    )

    expect(html).toContain("2 keywords")
    expect(html).toContain("× 2 ad groups")
    expect(html).toContain("4 proposed changes")
    expect(html).toContain("Exact — Brand")
    expect(html).toContain("Broad — Prospecting")
  })

  it("renders per-ad-group negative keyword removal rollups", () => {
    const html = render(
      googleAdsAdGroupNegativeKeywordsPresenter.render(
        props({
          id: "ad-group-negative-keywords-result",
          kind: "result",
          name: "google_ads_remove_ad_group_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { removed: 1, not_found: 1, failed: 1 },
                ad_groups: [
                  {
                    ad_group_id: "10",
                    ad_group_name: "Exact",
                    campaign_name: "Brand",
                    counts: { removed: 1, not_found: 1, failed: 1 },
                    ad_group_errors: [
                      {
                        text: "cheap",
                        match_type: "BROAD",
                        message: "This criterion could not be removed.",
                        error_code: "CANNOT_REMOVE_CRITERION",
                      },
                    ],
                    errors_truncated: false,
                    keyword_outcomes: [
                      {
                        text: "free",
                        match_type: "EXACT",
                        outcome: "removed",
                        external_ref: "customers/111/adGroupCriteria/10~1",
                      },
                      { text: "jobs", match_type: "PHRASE", outcome: "not_found" },
                      {
                        text: "cheap",
                        match_type: "BROAD",
                        outcome: "failed",
                        error_code: "CANNOT_REMOVE_CRITERION",
                      },
                    ],
                  },
                ],
                ad_groups_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain('aria-label="Google Ads ad group negative keyword results"')
    expect(html).toContain("Exact")
    expect(html).toContain("Brand")
    expect(html).toContain("Not found")
    expect(html).toContain("jobs")
    expect(html).toContain("This criterion could not be removed.")
  })

  it("renders exact completed campaign and ad-group keyword additions", () => {
    const campaignHtml = render(
      googleAdsCampaignNegativeKeywordsPresenter.render(
        props({
          id: "campaign-negative-keywords-add-result",
          kind: "result",
          name: "google_ads_add_campaign_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { added: 1, skipped_existing: 0, failed: 0 },
                campaigns: [
                  {
                    campaign_id: "10",
                    campaign_name: "Brand",
                    counts: { added: 1, skipped_existing: 0, failed: 0 },
                    campaign_errors: [],
                    errors_truncated: false,
                    keyword_outcomes: [
                      {
                        text: "free trial",
                        match_type: "PHRASE",
                        outcome: "added",
                        external_ref: "customers/111/campaignCriteria/10~1",
                      },
                    ],
                  },
                ],
                campaigns_truncated: false,
              }),
            ],
          },
        })
      )
    )
    const adGroupHtml = render(
      googleAdsAdGroupNegativeKeywordsPresenter.render(
        props({
          id: "ad-group-negative-keywords-add-result",
          kind: "result",
          name: "google_ads_add_ad_group_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { added: 1, skipped_existing: 0, failed: 0 },
                ad_groups: [
                  {
                    ad_group_id: "20",
                    ad_group_name: "Exact",
                    campaign_name: "Brand",
                    counts: { added: 1, skipped_existing: 0, failed: 0 },
                    ad_group_errors: [],
                    errors_truncated: false,
                    keyword_outcomes: [
                      {
                        text: "jobs near me",
                        match_type: "EXACT",
                        outcome: "added",
                        external_ref: "customers/111/adGroupCriteria/20~2",
                      },
                    ],
                  },
                ],
                ad_groups_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(campaignHtml).toContain("free trial")
    expect(campaignHtml).toContain("Phrase")
    expect(campaignHtml).toContain("Added")
    expect(campaignHtml).toContain("External Reference")
    expect(campaignHtml).not.toContain(">Details</span></th>")
    expect(campaignHtml).not.toContain("Error Code")
    expect(adGroupHtml).toContain("jobs near me")
    expect(adGroupHtml).toContain("Exact")
    expect(adGroupHtml).toContain("Added")
    expect(adGroupHtml).not.toContain(">Details</span></th>")
    expect(adGroupHtml).not.toContain("Error Code")
  })

  it.each([
    ["running", "Adding Google Ads negative keywords…"],
    ["awaiting_approval", "Waiting for negative keyword approval…"],
    ["denied", "Nothing was added."],
    ["failed", "No negative keyword change was confirmed."],
    ["unknown", "No negative keyword change was confirmed."],
  ] as const)("renders an honest negative-keyword %s state", (status, expected) => {
    const html = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props({
          id: "negative-keywords-state",
          kind: "call",
          name: "google_ads_add_negative_keywords",
          status,
          args: {
            negative_list: sharedSetReference("50", "Brand Protection"),
            keywords: [{ text: "free", match_type: "EXACT" }],
          },
        })
      )
    )
    expect(html).toContain(expected)
  })

  it.each([
    ["running", "Updating Google Ads campaigns…"],
    ["awaiting_approval", "Waiting for campaign approval…"],
    ["denied", "Nothing was changed."],
    ["failed", "No campaign change was confirmed."],
    ["unknown", "No campaign change was confirmed."],
  ] as const)("renders an honest %s lifecycle state", (status, expected) => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props({
          id: "campaign-1",
          kind: "call",
          name: "google_ads_update_campaign_status",
          status,
          args: { campaign_ids: [campaignReference("10", "Summer Sale")], status: "PAUSED" },
        })
      )
    )
    expect(html).toContain(expected)
  })

  it("falls through for malformed read payloads and registers all presenters", () => {
    expect(
      googleAdsReportPresenter.render(
        props({
          id: "report-1",
          kind: "result",
          name: "google_ads_run_report",
          status: "completed",
          result: { results: [entry({ rows: "bad" })] },
        })
      )
    ).toBeNull()
    expect(googleAdsModule.toolRowPresenters.map((presenter) => presenter.key)).toEqual([
      "google-ads-run-report",
      "google-ads-list-accounts",
      "google-ads-create-negative-keyword-list",
      "google-ads-list-negative-keywords",
      "google-ads-campaign-negative-keywords",
      "google-ads-ad-group-negative-keywords",
      "google-ads-negative-list-campaign-links",
      "google-ads-update-campaign-status",
    ])
    expect(googleAdsCampaignLinksPresenter.handlesApprovals).toBe(true)
    expect(googleAdsCampaignNegativeKeywordsPresenter.handlesApprovals).toBe(true)
    expect(googleAdsCampaignStatusPresenter.handlesApprovals).toBe(true)
    expect(googleAdsListNegativeKeywordsPresenter.handlesApprovals).toBe(true)
  })

  it("loads and renders the report presenter through the production registry seam", async () => {
    await loadIntegrationUiModules(["google_ads"])

    expect(integrationToolRowPresenters("google_ads").map((presenter) => presenter.key)).toContain(
      "google-ads-run-report"
    )
    const row = renderCustomToolCallRow(
      props({
        id: "report-registry-1",
        kind: "result",
        name: "google_ads_run_report",
        status: "completed",
        result: {
          results: [
            entry({
              rows: [],
              row_count: 0,
              truncated: false,
              truncation_note: null,
            }),
          ],
        },
      })
    )
    const html = render(row)

    expect(html).toContain('aria-label="Google Ads report results"')
    expect(html).toContain("Run Google Ads Report")
    expect(html).not.toContain("GAQL Query")
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<
    typeof googleAdsCampaignStatusPresenter.render
  >[0]["approvalDecision"],
  ui?: ToolUi
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ...(ui ? { ui } : {}),
  }
}

function field(
  key: string,
  label: string,
  format: ToolUiField["format"],
  editable = false
): ToolUiField {
  return { key, label, format, editable, secondary: false, options: [], placeholder: "" }
}

function toolUi(argFields: ToolUiField[]): ToolUi {
  return {
    approval_prompt: "",
    approval_title: "",
    approve_label: "",
    arg_fields: argFields,
    completed_label: "",
    failed_label: "",
    icon: "google_ads",
    result_fields: [],
    running_label: "",
  }
}

function campaignReference(externalId: string, label: string) {
  return {
    version: 1,
    entity_kind: "google_ads_campaign",
    integration_resource_id: "resource-1",
    external_id: externalId,
    label,
  }
}

function adGroupReference(externalId: string, label: string, campaign: string) {
  return {
    version: 1,
    entity_kind: "google_ads_ad_group",
    integration_resource_id: "resource-1",
    external_id: externalId,
    label,
    scope_label: campaign,
  }
}

function sharedSetReference(externalId: string, label: string) {
  return {
    version: 1,
    entity_kind: "google_ads_shared_set",
    integration_resource_id: "resource-1",
    external_id: externalId,
    label,
  }
}

function entry(data: unknown) {
  return {
    connection_id: "connection-1",
    display_name: "Client account",
    external_id: "1234567890",
    status: "success",
    data,
    error_message: null,
  }
}

function approvalControls() {
  return {
    decision: { decision: "pending" as const, edits: {}, message: "" as const },
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}

function assertCustomApproval(
  activity: ToolActivity,
  controls: ReturnType<typeof approvalControls>,
  rows: Record<string, string | number>[],
  expectedTotal: string,
  expectedCount: string
) {
  controls.decision.edits = { keywords: rows }
  const rendered = googleAdsListNegativeKeywordsPresenter.render(
    props(activity, controls, toolUi([]))
  )

  expect(isValidElement(rendered)).toBe(true)
  if (isValidElement<{ controls: unknown }>(rendered)) {
    expect(rendered.type).toBe(ToolApprovalDecisionCard)
    expect(rendered.props.controls).toBe(controls)
  }
  const html = render(rendered)
  expect(html).toContain(expectedTotal)
  expect(html).toContain(expectedCount)
  expect(html).toContain("Approve &amp; Add")
  expect(html).toContain("Decline")
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
