// apps/web/tests/integrations/outlook_mail/preview-interaction.tsx

import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { OutlookMessageRow } from "@/integrations/outlook_mail/components/message"
import { GmailMessageView } from "@/integrations/gmail/components/message-preview"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import "@/index.css"

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}
function element(id: string): HTMLElement {
  const found = document.getElementById(id)
  assert(found, `The harness page has a #${id} element`)
  return found
}

const container = element("root")
const status = element("status")
const root = createRoot(container)
const queryClient = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } })
const message = {
  mailboxId: "mailbox",
  messageId: "A+/==",
  subject: "Report",
  sender: "dana@example.com",
  receivedAt: "2026-09-08T10:00:00Z",
  preview: "Summary",
  unread: true,
  important: false,
  hasAttachments: false,
}
const requests: URL[] = []
let respond: ((value: Response) => void) | undefined
const originalFetch = window.fetch.bind(window)
window.fetch = (input) => {
  requests.push(new URL(requestUrl(input)))
  return new Promise<Response>((resolve) => {
    respond = resolve
  })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input
  return input instanceof URL ? input.href : input.url
}
// Counts polls rather than reading the clock so headless virtual time cannot expire the wait.
async function until(condition: () => boolean, step: string) {
  for (let attempt = 0; attempt < 500; attempt += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  throw new Error(`Timed out waiting for: ${step}`)
}
// Reading the length through a call keeps TypeScript from narrowing it to a literal.
function countRequests() {
  return requests.length
}
async function requestCount(count: number) {
  await until(() => countRequests() === count, `${String(count)} preview requests`)
}
function lastRequest(): URL {
  const request = requests.at(-1)
  assert(request, "A preview request was made")
  return request
}
function pageText() {
  return document.body.textContent
}
function previewFrame() {
  return document.querySelector("iframe")
}
async function toggle() {
  const button = container.querySelector("button")
  assert(button, "The message row has an opening control")
  const wasOpen = previewFrame() !== null || pageText().includes("Loading message preview")
  button.click()
  if (wasOpen) await until(() => previewFrame() === null, "the preview to close")
}
function reply(content: string, contentType = "html", meta = {}) {
  assert(respond, "A preview request is pending")
  respond(
    Response.json({
      kind: "outlook_message",
      content_type: contentType,
      content,
      meta: { subject: "Report", ...meta },
    })
  )
}
function fail() {
  assert(respond, "A preview request is pending")
  respond(new Response("Unavailable", { status: 500 }))
}
let mounts = 0
async function mount(conversation = "conversation", mailboxId = "mailbox", gmail = false) {
  mounts += 1
  const marker = String(mounts)
  root.render(
    <QueryClientProvider client={queryClient}>
      <ToolConversationContext value={conversation}>
        <div data-mount={marker} />
        {gmail ? (
          <GmailMessageView
            mailboxId={mailboxId}
            messageId="gmail-message"
            fallback={<p>Gmail fallback</p>}
          />
        ) : (
          <OutlookMessageRow
            key={`${conversation}:${mailboxId}`}
            message={{ ...message, mailboxId }}
          />
        )}
      </ToolConversationContext>
    </QueryClientProvider>
  )
  await until(() => container.querySelector(`[data-mount="${marker}"]`) !== null, "mount")
}
async function run() {
  setActiveWorkspaceSlug("workspace-a")
  await mount()
  assert(countRequests() === 0, "Closed rows do not fetch previews")
  await toggle()
  await requestCount(1)
  assert(pageText().includes("Loading message preview"), "Opening shows a loading state")
  const first = lastRequest()
  assert(
    first.pathname.endsWith("/integrations/conversations/conversation/previews/outlook_message"),
    "Uses the conversation preview route"
  )
  assert(first.searchParams.get("ref") === "A+/==", "Preserves immutable IDs")
  assert(first.searchParams.get("scope_id") === "mailbox", "Scopes the preview to its mailbox")
  reply("<p>Preview body</p>")
  await until(() => previewFrame() !== null, "the HTML preview frame")
  const frame = previewFrame()
  assert(frame, "The preview renders in a frame")
  assert(frame.getAttribute("sandbox") === "", "Preview frames have no sandbox capabilities")
  assert(
    frame.srcdoc.includes("Preview body") && frame.srcdoc.includes("default-src 'none'"),
    "HTML uses the constrained content frame"
  )
  await toggle()
  assert(previewFrame() === null, "Closing unmounts the preview")
  await toggle()
  await until(() => previewFrame() !== null, "the cached preview frame")
  assert(countRequests() === 1, "Repeated opening reuses the cached preview")

  await mount("conversation", "other-mailbox")
  await toggle()
  await requestCount(2)
  fail()
  await requestCount(3)
  fail()
  await until(
    () => pageText().includes("This message preview could not be loaded"),
    "the error state"
  )

  await mount("other-conversation")
  await toggle()
  await requestCount(4)
  reply("Other conversation", "text")
  await until(() => pageText().includes("Other conversation"), "the other conversation preview")
  setActiveWorkspaceSlug("workspace-b")
  await mount("conversation")
  await toggle()
  await requestCount(5)
  reply("Other workspace", "text")
  await until(() => pageText().includes("Other workspace"), "the other workspace preview")

  await mount("conversation", "mailbox", true)
  await requestCount(6)
  assert(container.textContent.includes("Gmail fallback"), "Gmail preserves its loading fallback")
  reply("Gmail body", "text", { labels: ["Inbox"], thread_message_count: 3 })
  await until(() => container.textContent.includes("Gmail body"), "the Gmail preview")
  assert(
    container.textContent.includes("Inbox") && container.textContent.includes("3 Messages"),
    "Gmail retains metadata chips"
  )
  await mount("conversation", "gmail-failure", true)
  await requestCount(7)
  fail()
  await requestCount(8)
  fail()
  await until(
    () =>
      queryClient
        .getQueryCache()
        .getAll()
        .some(
          (query) => query.state.status === "error" && query.queryKey.includes("gmail-failure")
        ),
    "the Gmail query error"
  )
  assert(container.textContent.includes("Gmail fallback"), "Gmail preserves its error fallback")
  status.textContent =
    "PASS: opening, loading, success, failure, cached reopening, context isolation, sandbox, and Gmail metadata/fallback"
}
run()
  .catch((error: unknown) => {
    status.textContent = `FAIL: ${String(error)}`
  })
  .finally(() => {
    window.fetch = originalFetch
  })
