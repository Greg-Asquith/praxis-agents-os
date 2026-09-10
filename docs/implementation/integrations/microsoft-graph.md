# Microsoft Graph implementation

Read this when changing Microsoft Graph connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

## Backend contracts

The engine-owned `services/integrations/microsoft_graph/` seam provides
global-cloud Entra authority validation, delegated identity, stable error
mapping, pacing, bounded pagination and downloads, and the Outlook
immutable-ID request rule. Discovery receives an opaque connection pacing
key. Partial results must identify failed resource parents so reconciliation
preserves their existing resources while the connection remains degraded.
Authentication failures must propagate to credential refresh and connection
recovery. The seam must not import provider packages. The Outlook
Mail, Outlook Calendar, and SharePoint packages each own isolated OAuth
settings and discovery. They expose `outlook_mailbox`, `outlook_calendar`,
and `sharepoint_drive` resources, respectively. Calendar and SharePoint tools
are pending.

`MicrosoftGraphClient.get_graph_bytes(path, operation=..., max_bytes=...)`
reads authenticated binary Graph responses, including attachment `/$value`
endpoints. It restricts credentials to the global Graph host, refuses
redirects, checks both declared and streamed byte counts, and retains
immutable IDs, per-attempt pacing, read retries, and one refresh after a 401.
Download errors use the shared HTTP status mapping without retaining provider
bodies or transport exceptions. Declared and streamed size overflow raises
`IntegrationDownloadTooLargeError` with rejected disposition. Partial streams
are discarded before retry.
`get_bytes` remains the separate download method for pre-authenticated public
URLs and sends no bearer token.

## Frontend contracts

The three Microsoft modules contribute isolated logos, catalogue descriptions,
and shared administrator setup and removal guidance. Outlook Mail contributes
registered custom read-result presenters for success, error, and partial
fan-out results. The scalar declarative field renderer cannot display these
structured results. Message and attachment presenters retain their rich views.
Folder and people results use the shared DataTable with sorting, pagination,
copy, and CSV export. Folder counts remain numeric. Outlook result headers
include the provider icon and mailbox names without opaque mailbox identifiers.
Search rows open the full message in the shared `MessagePreviewRow` popover,
and the read view replaces the plain body with the fetched message, matching
Gmail. Both use the shared `provider-content-preview.tsx` loader.
Shared chat search previews show an unavailable state without provider requests;
completed reads retain the saved message body. Gmail retains
its metadata chips and query keys through that same loader. HTML previews use
engine sanitisation and the script-less sandboxed frame.

## Outlook Mail reads

Select an Outlook mailbox in Active Context to use these tools:

- `outlook_mail_search_messages` searches a folder with optional KQL, an unread
  filter, and up to 25 results. Without KQL, results list newest first. With
  KQL, unread filtering checks at most twice the requested result count.
- `outlook_mail_read_message` targets one scoped message reference and returns
  up to 50,000 body characters, 50 recipients per field, and 50 attachments.
- `outlook_mail_list_folders` lists up to 200 top-level folders. Folder inputs
  accept a well-known name or the first exact display-name match.
- `outlook_mail_read_attachment` targets one scoped file attachment and
  returns up to 64 KiB of converted Markdown. Embedded items, reference
  attachments, images, unsupported types, and oversized files fail closed.
- `outlook_mail_search_people` resolves a name to up to 25 people, including
  email addresses, job titles, and departments. It uses email-address fields,
  then an email-shaped user principal name. People without either are omitted.

Reads use the existing audited context runners and work in Code Mode.
Searches fan out across compatible mailboxes; references require exactly one
matching active mailbox. Message picker searches exclude ambiguous mailboxes
before provider requests. Results include the mailbox time zone. Provider text
uses `outlook_message` or `outlook_person` provenance nodes, with a 768 KiB
limit on the complete serialised result.

`OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES` defaults to 26,214,400 bytes and must be
positive. Both attachment metadata and streamed download bytes enforce it.
Metadata, declared download length, and streamed overflow report
`attachment_too_large`
in tool results and operation audits.
The `outlook_message` preview returns raw content to the engine for bounding
and sanitisation. Preview definitions validate provider-specific reference
patterns: Outlook permits bounded base64 IDs; Gmail retains its short URL-safe
IDs.

## Outlook Mail writes

Select exactly one Outlook mailbox to use these approval-gated tools:

- `outlook_mail_send_message` creates a draft and submits it for sending.
- `outlook_mail_send_draft` submits an existing unsent draft by its message
  reference, including a reply draft saved earlier.
- `outlook_mail_reply_to_message` creates a reply draft, with optional
  **Reply all**, and submits it for sending.
- `outlook_mail_forward_message` forwards a message to the approved recipients.
- `outlook_mail_create_draft` saves either a new message with To and Subject,
  or a reply with a message reference. Nothing is sent.
- `outlook_mail_move_message` moves a message to a well-known folder or the
  first exact display-name match among up to 200 folders.
- `outlook_mail_update_message` changes Read, Flagged, or both. An omitted
  value leaves that property unchanged.

All seven tools work in Code Mode and require approval by default. Move and
update also support automatic execution under the operator's configured
policy. References must belong to the single selected mailbox. Read-only
mailboxes produce the shared write-denial audit without a provider request.

Recipient fields accept up to 100 plain addresses each. Subjects are bounded
to 998 characters and outbound bodies to 50,000 characters. Outbound HTML
uses the shared preview sanitiser. Replies and forwards prepend that approved
HTML to the draft's quoted HTML without rewriting the quote. A missing,
non-HTML, empty, or oversized quote stops the operation and leaves the draft.
Tenant verification of quoted conversation rendering remains pending.

Approval display arguments include default values while replay arguments
remain separate. Optional reply targets remain null when another field
changes.

To finish a draft workflow, use `outlook_mail_send_draft` with the reference
returned by `outlook_mail_create_draft`. Reply and send-message tools create
another draft and are not substitutes for sending the saved draft.

Send-draft approval shows a read-only snapshot of From, Sender, To, Cc, Bcc,
Reply to, Subject, and the message. Provider HTML uses the shared sanitised
preview frame. The server retains the snapshot separately from model and
replay arguments. The approved run and tool-call identity bind the retained
snapshot for direct and Code Mode calls. Before recording pending send intent,
the tool re-reads the draft and compares its version and complete reviewed
fields. Changed or already-sent drafts fail before submission and need a new
approval. The send request uses the same immutable ID and leaves the body and
thread unchanged. Drafts with attachments, including inline attachments, are
unsupported and must be sent in Outlook. Generated replies and forwards use
the same attachment collection check before sending. Incomplete collection
data blocks sending and retains the known draft reference and completed effects.
The check leaves attachments and quoted content intact. Missing or oversized
review data fails closed.

Graph's [send-draft action](https://learn.microsoft.com/en-us/graph/api/message-send?view=graph-rest-1.0)
does not document a conditional version header. The read-before-send check
cannot prevent a concurrent Outlook edit between that check and submission.

Each write has its own tool row presenter under
`apps/web/src/integrations/outlook_mail/presenters/`, built on the shared
write seam described in the [integration guide](README.md#shared-presenter-seams).
The Outlook adapter supplies the mailbox branding, per-tool copy, argument
parsers, and the outcome view; the seam owns approvals, lifecycle states, and
fan-out cards. Approval cards edit the server-declared fields and block resume
with a plain reason when a draft mixes reply and new-message fields or an
update changes nothing. Outcome cards show the approved subject, recipients,
folder, or flags and the approved source message label. Saved-draft outcomes
prefer the retained reviewed subject, with the reference label as a fallback.
Cards keep the source distinct from any returned message or created draft.
They show the approved HTML in the shared sandboxed frame, and an
**Open in Outlook** link from the result's web link. Failed results inside a
successful mailbox entry render as failed cards with the known draft reference;
unverified results render as unconfirmed. When a returned reference has no safe
web link, **View returned message** opens the existing scoped message preview
through the shared API client. The retained mailbox and message identity select
the preview; an unavailable message shows an unavailable state without
constructing an Outlook URL or claiming the draft still exists. Sending a saved draft reviews it as
a read-only email header and message, because the draft is sent exactly as
saved. A sending result means Outlook accepted the request, rather than
confirming delivery.

Reply-draft approvals preserve null To, Cc, and Bcc as Outlook reply
inheritance and list those fields in `_recipient_inheritance` display metadata.
An explicit empty Cc or Bcc clears that field. The approval card describes
inheritance and offers a clear action. Editing another field preserves the
original recipient intent. Replay excludes display metadata. Pending evidence
uses `to_source`, `cc_source`, or `bcc_source` with `outlook_reply` for
unresolved inherited recipients, and counts only explicit lists.

The shared runtime records pending intent before mutation and correlated
terminal evidence afterwards. Pending evidence contains recipient counts,
flags, and the resolved folder name, never subjects or bodies. Draft IDs use
Graph's immutable-ID header and remain available in results and audit records
if sending fails. A rejected send returns `send_failed` and reports that the
send request failed. Check the message in Outlook before trying again because
its continued existence and folder are unknown. Ambiguous failures return
`unverified_mutation` and
must not be retried automatically. Cancellation retains terminal evidence
and propagates to the runtime.

Write tools supply `MailWriteCallbacks` from `tools/utils.py` to the shared
audit runner. Each preparation callback returns a `PreparedMailWrite` with
pending evidence and the mutation to execute. The callbacks share cancellation
and outcome handling. The shared runner owns audit persistence and invokes the
mutation only after recording pending intent.

## Operator setup

Follow the [Microsoft Entra app registration guide](../../guides/microsoft-entra-app-registration.md).
