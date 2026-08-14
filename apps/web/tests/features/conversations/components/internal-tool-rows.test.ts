// apps/web/tests/features/conversations/components/internal-tool-rows.test.ts

import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import {
  DelegateAgentListRow,
  DelegationToolRow,
} from "@/features/conversations/components/delegation-tool-row"
import { ArtifactToolRow } from "@/features/conversations/components/artifact-tool-row"
import { FileToolRow } from "@/features/conversations/components/file-tool-row"
import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import { SkillDocumentReadRow } from "@/features/conversations/components/skill-document-read-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { skillsQueryOptions } from "@/features/skills/api/list-skills"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"
import { filesQueryKeys } from "@/features/files/api/list-files"

describe("delegation tool rows", () => {
  it("renders available agents through a result card and a running skeleton", () => {
    const completed = render(
      createElement(DelegateAgentListRow, {
        activity: activity({
          name: "list_delegate_agents",
          result: [
            { id: "agent-1", name: "Research Agent", description: "Checks source material." },
          ],
        }),
        defaultOpen: true,
      })
    )
    const running = render(
      createElement(DelegateAgentListRow, {
        activity: activity({ name: "list_delegate_agents", status: "running", result: undefined }),
        defaultOpen: false,
      })
    )

    expect(completed).toContain("Available Agents")
    expect(completed).toContain("1 Agent")
    expect(completed).toContain("Research Agent")
    expect(completed).toContain("Checks source material.")
    expect(completed).toContain(">Details<")
    expect(completed).not.toContain('data-slot="tool-field-well"')
    expect(running).toContain('aria-busy="true"')
    expect(running).toContain("Finding available agents…")
  })

  it("renders completed and failed delegate outcomes with honest status copy", () => {
    const completed = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({
          output: "**The source review** is complete.",
          status: "completed",
        }),
        defaultOpen: true,
      })
    )
    const failed = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({
          error: "The delegated model could not finish.",
          status: "failed",
        }),
        defaultOpen: false,
      })
    )
    const denied = render(
      createElement(DelegationToolRow, {
        activity: {
          ...delegationActivity({ status: "running" }),
          status: "denied",
        },
        defaultOpen: false,
      })
    )
    const running = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({ status: "running" }),
        defaultOpen: false,
      })
    )

    expect(completed).toContain("Research Agent")
    expect(completed).toContain("Task")
    expect(completed).toContain("<strong")
    expect(completed).toContain("The source review</strong> is complete.")
    expect(completed).not.toContain("**The source review**")
    expect(completed).toContain("whitespace-normal")
    expect(completed).toContain(">Done<")
    expect(completed).not.toContain('data-slot="tool-field-well"')
    expect(failed).toContain("The delegated model could not finish.")
    expect(failed).toContain(">Failed<")
    expect(failed).toContain('aria-expanded="true"')
    expect(denied).toContain("This delegation was declined, so no work was started.")
    expect(denied).toContain(">Declined<")
    expect(denied).not.toContain("Delegating to Research Agent…")
    expect(running).toContain("Delegating to Research Agent…")
    expect(running).toContain('aria-busy="true"')
  })

  it("uses the shared approval card and preserves its controls contract", () => {
    const controls = approvalControls()
    const html = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({ status: "awaiting_approval" }),
        approvalDecision: controls,
        defaultOpen: false,
      })
    )

    expect(html).toContain("Delegate to Research Agent")
    expect(html).toContain("Approve &amp; Delegate")
    expect(html).toContain("Decline")
    expect(html).toContain("Review launch evidence")
    expect(html).toContain("Delegate to Agent")
    expect(html).toContain("<textarea")
    expect(controls.onDecisionChange).not.toHaveBeenCalled()
  })

  it("shows the delegated tool parameters in its approval card", () => {
    const controls = approvalControls()
    const html = render(
      createElement(DelegationToolRow, {
        activity: {
          ...delegationActivity({ status: "awaiting_approval", taskPreview: null }),
          args: { dry_run: true, value: "external mutation" },
          kind: "approval",
          name: "delegated_external_write",
          status: "awaiting_approval",
        },
        approvalDecision: controls,
        defaultOpen: false,
      })
    )

    expect(html).toContain("Research Agent: External Write")
    expect(html).toContain("Review the parameters before approving.")
    expect(html).toContain("Value")
    expect(html).toContain("external mutation")
    expect(html).toContain("Dry Run")
    expect(html).toContain(">Yes<")
    expect(html).toContain(">Approve<")
    expect(html).not.toContain("Approve &amp; Delegate")
    expect(controls.onDecisionChange).not.toHaveBeenCalled()
  })

  it("falls back to readable parameters for delegated tools without presentation metadata", () => {
    const html = render(
      createElement(DelegationToolRow, {
        activity: {
          ...delegationActivity({ status: "awaiting_approval", taskPreview: null }),
          args: { attempts: 2, recipient: "ops@example.com" },
          kind: "approval",
          name: "custom_external_action",
          status: "awaiting_approval",
        },
        approvalDecision: approvalControls(),
        defaultOpen: false,
      })
    )

    expect(html).toContain("custom_external_action")
    expect(html).toContain("Attempts")
    expect(html).toContain(">2<")
    expect(html).toContain("Recipient")
    expect(html).toContain("ops@example.com")
  })

  it("returns null for unexpected list and delegation shapes", () => {
    expect(
      render(
        createElement(DelegateAgentListRow, {
          activity: activity({ name: "list_delegate_agents", result: { agents: [] } }),
          defaultOpen: false,
        })
      )
    ).toBe("")
    expect(
      render(
        createElement(DelegationToolRow, {
          activity: activity({ name: "delegate_to_agent" }),
          defaultOpen: false,
        })
      )
    ).toBe("")
  })
})

describe("artifact tool rows", () => {
  it("renders completed artifacts as actionable entity cards", () => {
    const html = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          name: "create_artifact",
          result: {
            artifact_id: "artifact-1",
            version_id: "version-1",
            title: "Quarterly report",
            artifact_type: "html",
          },
        }),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Create Artifact")
    expect(html).toContain("Quarterly report")
    expect(html).toContain("HTML artifact")
    expect(html).toContain('aria-label="Open artifact Quarterly report"')
    expect(html).toContain(">Open<")
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("renders honest running, denied, and malformed states", () => {
    const preparing = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          args: null,
          name: "create_artifact",
          status: "running",
          result: undefined,
        }),
        defaultOpen: false,
      })
    )
    const running = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          args: { title: "Launch map" },
          name: "update_artifact",
          status: "running",
          result: undefined,
        }),
        defaultOpen: false,
      })
    )
    const denied = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          name: "create_artifact",
          status: "denied",
          result: undefined,
        }),
        defaultOpen: false,
      })
    )
    const malformed = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          name: "create_artifact",
          result: { artifact_id: "artifact-1" },
        }),
        defaultOpen: false,
      })
    )

    expect(preparing).toContain("Creating artifact…")
    expect(preparing).toContain('aria-busy="true"')
    expect(running).toContain("Updating artifact…")
    expect(running).toContain("Launch map")
    expect(running).toContain('aria-busy="true"')
    expect(denied).toContain("This artifact change was declined. Nothing was saved.")
    expect(denied).toContain(">Declined<")
    expect(malformed).toBe("")
  })

  it("renders artifact discovery as linked workspace entities", () => {
    const html = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          args: { search: "quarterly" },
          name: "list_artifacts",
          result: {
            items: [
              {
                id: "artifact-1",
                reference: artifactReference("artifact-1", "Quarterly report"),
                title: "Quarterly report",
                artifact_type: "markdown",
                version_count: 3,
                updated_at: "2026-08-14T10:00:00Z",
                conversation_id: "conversation-1",
              },
              {
                id: "artifact-2",
                reference: artifactReference("artifact-2", "Revenue chart"),
                title: "Revenue chart",
                artifact_type: "image-ref",
                version_count: 1,
                updated_at: "2026-08-13T10:00:00Z",
                conversation_id: null,
              },
            ],
            total: 4,
            returned: 2,
          },
        }),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Artifacts")
    expect(html).toContain("4 Artifacts")
    expect(html).toContain("Search: quarterly")
    expect(html).toContain('aria-label="Artifact results"')
    expect(html).toContain('href="/artifacts/artifact-1"')
    expect(html).toContain("Quarterly report")
    expect(html).toContain("3 versions")
    expect(html).toContain("Revenue chart")
    expect(html).toContain("Image")
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("renders current artifact content and honest binary metadata", () => {
    const text = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          name: "read_artifact",
          result: {
            id: "artifact-1",
            reference: artifactReference("artifact-1", "Quarterly report"),
            title: "Quarterly report",
            artifact_type: "markdown",
            revision_number: 3,
            updated_at: "2026-08-14T10:00:00Z",
            content: "# Revised report",
            truncated: true,
            size_bytes: 72_000,
            content_type: "text/markdown",
          },
        }),
        defaultOpen: true,
      })
    )
    const image = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          name: "read_artifact",
          result: {
            id: "artifact-2",
            reference: artifactReference("artifact-2", "Revenue chart"),
            title: "Revenue chart",
            artifact_type: "image-ref",
            revision_number: 1,
            updated_at: "2026-08-14T10:00:00Z",
            content: null,
            truncated: false,
            size_bytes: 1024,
            content_type: "image/png",
          },
        }),
        defaultOpen: true,
      })
    )

    expect(text).toContain("Read Artifact")
    expect(text).toContain('href="/artifacts/artifact-1"')
    expect(text).toContain("Revision 3")
    expect(text).toContain("Showing the first part of this artifact")
    expect(text).toContain('aria-label="Artifact content view"')
    expect(text).toContain('aria-selected="true"')
    expect(text).toContain("Rendered")
    expect(text).toContain("Raw")
    expect(text).toContain(">Revised report</h1>")
    expect(image).toContain("Preview this image in Artifacts")
    expect(image).toContain("Binary artifact content is not included")
    expect(image).not.toContain("download_url")
    expect(image).not.toContain("sig=")
  })

  it("renders discovery progress using the operator-visible artifact label", () => {
    const listing = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          args: { search: "launch" },
          name: "list_artifacts",
          status: "running",
          result: undefined,
        }),
        defaultOpen: false,
      })
    )
    const reading = render(
      createElement(ArtifactToolRow, {
        activity: activity({
          args: { artifact_id: artifactReference("artifact-1", "Launch map") },
          name: "read_artifact",
          status: "running",
          result: undefined,
        }),
        defaultOpen: false,
      })
    )

    expect(listing).toContain("Finding artifacts…")
    expect(listing).toContain("launch")
    expect(reading).toContain("Reading artifact…")
    expect(reading).toContain("Launch map")
  })
})

describe("skill tool rows", () => {
  it("renders activation as a non-expandable heading-only card", () => {
    const html = render(
      createElement(SkillActivationRow, {
        activity: activity({
          args: { id: "skill:skill-1" },
          name: "load_capability",
          toolKind: "capability-load",
        }),
      }),
      { seedSkills: true }
    )

    expect(html).toContain("Activated Skill: Source Research")
    expect(html).toContain(">Done<")
    expect(html).not.toContain("Expand results")
    expect(html).not.toContain(">Details<")
  })

  it("renders skill documents, running state, errors, and malformed fallback", () => {
    const completed = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({
          args: { document: "guide", skill: "research" },
          name: "read_skill_document",
          result:
            "<skill-document skill='research' document='guide'>\n# Guidance\nUse primary sources.\n</skill-document>",
        }),
        defaultOpen: true,
      })
    )
    const running = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({
          args: { document: "guide", skill: "research" },
          name: "read_skill_document",
          status: "running",
          result: undefined,
        }),
      })
    )
    const failed = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({
          name: "read_skill_document",
          status: "failed",
          result: "The document is no longer available.",
        }),
        defaultOpen: true,
      })
    )
    const malformed = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({ name: "read_skill_document", result: { content: "unexpected" } }),
      })
    )

    expect(completed).toContain("Read Skill Document")
    expect(completed).toContain("Guidance")
    expect(completed).toContain("Use primary sources.")
    expect(completed).not.toContain("&lt;skill-document")
    expect(completed).not.toContain('data-slot="tool-field-well"')
    expect(running).toContain("Reading skill document…")
    expect(running).toContain('aria-busy="true"')
    expect(failed).toContain("What Went Wrong")
    expect(failed).toContain("The document is no longer available.")
    expect(malformed).toBe("")
  })
})

describe("file tool rows", () => {
  it("renders generated images through the existing file outcome row", () => {
    const html = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "generate_image",
          result: {
            file_id: "generated-file-1",
            height: 1024,
            media_type: "image/png",
            name: "paper-cut-fox.png",
            revision_id: "generated-revision-1",
            size_bytes: 2048,
            width: 1536,
          },
        }),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Generate Image")
    expect(html).toContain("paper-cut-fox.png")
    expect(html).toContain("1536 x 1024")
    expect(html).toContain("2.0 KB")
    expect(html).toContain("mx-auto")
  })

  it("renders the editable generate-image approval instead of a loading skeleton", () => {
    const html = render(
      createElement(FileToolRow, {
        activity: activity({
          args: { prompt: "A cute red panda", aspect_ratio: "1:1", model_provider: "google" },
          kind: "approval",
          name: "generate_image",
          status: "awaiting_approval",
          result: undefined,
        }),
        approvalDecision: approvalControls(),
        defaultOpen: true,
        label: "Generate Image",
        ui: {
          approval_prompt: "Review the image prompt before approving.",
          approval_title: "Generate an Image",
          approve_label: "Approve & Generate",
          arg_fields: [
            {
              editable: true,
              format: "multiline",
              key: "prompt",
              label: "Prompt",
              min_rows: 0,
              options: [],
              placeholder: "Describe the image to generate",
              secondary: false,
            },
            {
              editable: true,
              format: "text",
              key: "model_provider",
              label: "Image Provider",
              min_rows: 0,
              options: ["google", "openai"],
              placeholder: "",
              secondary: false,
            },
          ],
          completed_label: "Generated {name}",
          failed_label: "Couldn't Generate the Image",
          icon: "image",
          result_fields: [],
          running_label: "Generating an Image",
        },
      })
    )

    expect(html).toContain("Generate an Image")
    expect(html).toContain("A cute red panda")
    expect(html).toContain("Creates New Image")
    expect(html).toContain("Image Provider")
    expect(html).toContain("Google")
    expect(html).toContain("Approve &amp; Generate")
    expect(html).not.toContain('aria-busy="true"')
  })

  it.each([
    ["edit_image", "Edit Image", "hero.png", "Creates Edited Image", "Approve & Edit"],
    [
      "generate_image_from_video",
      "Generate Image from Video",
      "launch.mov",
      "Creates New Image",
      "Approve & Generate",
    ],
  ])(
    "renders governed input media for %s approvals",
    (name, title, sourceName, badge, approveLabel) => {
      const isEdit = name === "edit_image"
      const sourceReference = { entity_id: "source-file-1", label: sourceName }
      const html = render(
        createElement(FileToolRow, {
          activity: activity({
            args: isEdit
              ? { prompt: "Match our palette", file_ids: [sourceReference] }
              : { prompt: "Create a launch thumbnail", file_id: sourceReference },
            kind: "approval",
            name,
            status: "awaiting_approval",
            result: undefined,
          }),
          approvalDecision: approvalControls(),
          defaultOpen: true,
          label: title,
          ui: {
            approval_prompt: "Review the source media and prompt.",
            approval_title: title,
            approve_label: approveLabel,
            arg_fields: [
              {
                editable: true,
                format: "multiline",
                key: "prompt",
                label: "Prompt",
                min_rows: 0,
                options: [],
                placeholder: "Describe the result",
                secondary: false,
              },
              {
                editable: false,
                format: isEdit ? "entity_list" : "entity",
                key: isEdit ? "file_ids" : "file_id",
                label: isEdit ? "Source Images" : "Source Video",
                min_rows: 0,
                options: [],
                placeholder: "",
                secondary: false,
                entity_kind: "file",
              },
            ],
            completed_label: "Generated {name}",
            failed_label: "Couldn't create the image",
            icon: "image",
            result_fields: [],
            running_label: title,
          },
        }),
        { previews: { "source-file-1": "https://files.example/source-preview" } }
      )

      expect(html).toContain(title)
      expect(html).toContain(sourceName)
      expect(html).toContain(badge)
      expect(html).toContain(approveLabel.replaceAll("&", "&amp;"))
      expect(html).toContain(isEdit ? "<img" : "<video")
      expect(html).toContain("https://files.example/source-preview")
      expect(html).not.toContain('aria-busy="true"')
    }
  )

  it.each([
    ["edit_image", "Edit Image"],
    ["generate_image_from_video", "Generate Image from Video"],
  ])("renders %s results through the existing image outcome row", (name, heading) => {
    const html = render(
      createElement(FileToolRow, {
        activity: activity({
          name,
          result: {
            file_id: "generated-file-2",
            height: 768,
            media_type: "image/png",
            name: "derived-image.png",
            revision_id: "generated-revision-2",
            size_bytes: 1024,
            width: 1024,
          },
        }),
        defaultOpen: true,
      })
    )

    expect(html).toContain(heading)
    expect(html).toContain("derived-image.png")
    expect(html).toContain("1024 x 768")
  })

  it("renders file lists with details and preserves file entities", () => {
    const html = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "list_files",
          result: {
            files: [
              {
                id: "file-1",
                name: "brief.md",
                category: "editable_text",
                media_type: "text/markdown",
                size_bytes: 128,
                processing_status: "ready",
                updated_at: "2026-07-24T10:00:00Z",
              },
            ],
            total: 1,
          },
        }),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Workspace Files")
    expect(html).toContain("1 File")
    expect(html).toContain("brief.md")
    expect(html).toContain(">Details<")
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("renders running and failed file states without claiming success", () => {
    const running = render(
      createElement(FileToolRow, {
        activity: activity({ name: "read_file", status: "running", result: undefined }),
        defaultOpen: false,
      })
    )
    const failed = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "write_file",
          status: "failed",
          result: "Storage was unavailable.",
        }),
        defaultOpen: false,
      })
    )

    expect(running).toContain("Reading file…")
    expect(running).toContain('aria-busy="true"')
    expect(failed).toContain("Storage was unavailable.")
    expect(failed).toContain(">Failed<")
    expect(failed).not.toContain(">Done<")
  })

  it("keeps the existing file target visible while an edit awaits approval", () => {
    const html = render(
      createElement(FileToolRow, {
        activity: activity({
          args: {
            name: "ignored-name.md",
            file_id: "file-existing-1",
            expected_current_revision_id: "revision-4",
            content: "[staged for approval; content omitted]",
          },
          kind: "approval",
          name: "write_file",
          status: "awaiting_approval",
          result: undefined,
        }),
        approvalDecision: approvalControls(),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Updates Existing File")
    expect(html).toContain("file-existing-1")
    expect(html).toContain("revision-4")
    expect(html).toContain("update an existing workspace file")
    expect(html).toContain("Approve &amp; Save")
  })

  it("renders content metadata in Details and falls through for malformed results", () => {
    const completed = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "read_file",
          result: {
            mode: "content",
            content: "# Launch brief",
            end_offset: 14,
            file_id: "file-1",
            media_type: "text/markdown",
            name: "brief.md",
            offset: 0,
            total_bytes: 42,
            truncated: true,
          },
        }),
        defaultOpen: true,
      })
    )
    const malformed = render(
      createElement(FileToolRow, {
        activity: activity({ name: "read_file", result: { mode: "content" } }),
        defaultOpen: false,
      })
    )

    expect(completed).toContain("Content Read")
    expect(completed).toContain("0–14 bytes")
    expect(completed).toContain("This view is truncated. More content is available.")
    expect(completed).toContain("Launch brief")
    expect(malformed).toBe("")
  })
})

function render(
  element: ReactElement,
  options: { previews?: Record<string, string>; seedSkills?: boolean } = {}
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  for (const [fileId, url] of Object.entries(options.previews ?? {})) {
    queryClient.setQueryData(filesQueryKeys.preview(fileId), {
      expires_at: "2026-08-11T21:00:00Z",
      preview: { expires_at: "2026-08-11T21:00:00Z", url },
    })
  }
  queryClient.setQueryData(toolPresentationsQueryOptions().queryKey, {
    tools: [
      {
        effect: "write",
        label: "External Write",
        name: "delegated_external_write",
        provider: "praxis",
        ui: {
          approval_prompt: "Approve the external write.",
          approval_title: "External Write",
          approve_label: "Approve",
          arg_fields: [
            {
              editable: false,
              format: "text",
              key: "value",
              label: "Value",
              min_rows: 0,
              options: [],
              placeholder: "",
              secondary: false,
            },
            {
              editable: false,
              format: "boolean",
              key: "dry_run",
              label: "Dry Run",
              min_rows: 0,
              options: [],
              placeholder: "",
              secondary: false,
            },
          ],
          completed_label: "Wrote",
          failed_label: "Write Failed",
          icon: "tool",
          result_fields: [],
          running_label: "Writing",
        },
      },
      {
        effect: "write",
        label: "Delegate to Agent",
        name: "delegate_to_agent",
        provider: "praxis",
        ui: {
          approval_prompt: "Delegate this task.",
          approval_title: "Delegate to Agent",
          approve_label: "Approve & Delegate",
          arg_fields: [
            {
              editable: false,
              format: "text",
              key: "agent_id",
              label: "Agent",
              min_rows: 0,
              options: [],
              placeholder: "",
              secondary: false,
            },
            {
              editable: true,
              format: "multiline",
              key: "task",
              label: "Task",
              min_rows: 0,
              options: [],
              placeholder: "",
              secondary: false,
            },
          ],
          completed_label: "Delegated",
          failed_label: "Delegation Failed",
          icon: "bot",
          result_fields: [],
          running_label: "Delegating",
        },
      },
    ],
  })
  if (options.seedSkills) {
    queryClient.setQueryData(skillsQueryOptions({ includeInactive: true }).queryKey, {
      skills: [
        {
          id: "skill-1",
          name: "source-research",
          human_name: "Source Research",
          description: "Researches primary sources.",
          instructions: "Use primary sources.",
          workspace_id: "workspace-1",
          created_by: "user-1",
          documentation_refs: {},
          is_active: true,
          is_favorite: false,
          last_used_at: null,
          metadata: null,
          created_at: "2026-07-24T00:00:00Z",
          updated_at: "2026-07-24T00:00:00Z",
          deleted: false,
          deleted_at: null,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    })
  }
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: queryClient, children: element })
  )
}

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "tool-1",
    kind: "result",
    name: "tool",
    status: "completed",
    ...overrides,
  }
}

function artifactReference(entityId: string, label: string) {
  return {
    version: 1,
    entity_kind: "artifact",
    entity_id: entityId,
    label,
    description: "Artifact",
    scope_label: null,
  }
}

function delegationActivity(
  delegate: Partial<NonNullable<ToolActivity["delegate"]>>
): ToolActivity {
  return activity({
    args: { agent_id: "agent-1", task: "Review launch evidence" },
    name: "delegate_to_agent",
    status: delegate.status === "failed" ? "failed" : "completed",
    delegate: {
      agentId: "agent-1",
      agentName: "Research Agent",
      conversationId: null,
      error: null,
      output: null,
      pendingApprovalCount: 0,
      runId: "run-1",
      status: "completed",
      taskPreview: "Review launch evidence",
      truncated: false,
      ...delegate,
    },
  })
}

function approvalControls(): ToolApprovalDecisionControls {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    disabled: false,
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}
