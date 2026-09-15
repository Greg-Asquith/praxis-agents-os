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
and `sharepoint_drive` resources, respectively. Calendar tools are pending.

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
URLs and sends no bearer token. It pins public DNS addresses, refuses redirects
and non-200 downloads, and suppresses HTTP client diagnostics for the download
task so signed URLs do not enter logs. Concurrent requests keep their logging.
A download rejected with 423 reports `protected` without retaining the response.

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
Attachment reads report the shared converter's actual truncation state, so
literal marker text does not imply lost content. Text and HTML retain the
converter's default replacement decoding for invalid UTF-8 bytes.
The `outlook_message` preview returns raw content to the engine for bounding
and sanitisation. Preview definitions validate provider-specific reference
patterns: Outlook permits bounded base64 IDs; Gmail retains its short URL-safe
IDs.

## SharePoint and OneDrive file tools

Select libraries in Active Context to use `sharepoint_list_folder`.
Without a folder reference, it lists the root of every selected library.
With a reference, it targets exactly one selected drive and checks that the
item is a local folder before listing its children. Missing or ambiguous
drive selections stop before credential access. Remote shortcuts and items
with a different or missing parent drive are excluded. Package items, including
OneNote notebooks, are omitted and cannot be used as folder targets. Malformed
local file or folder metadata fails that library with a safe typed error;
other selected libraries retain their results.

Each library returns one page of up to `limit` items, with a default of 50
and a maximum of 200. `has_more` reports a continuation or an oversized
provider page; the tool does not follow continuation URLs. Results include
scoped references, names, kinds, parent paths, sizes, content types, modified
times, and citation URLs. Provider text uses `sharepoint_drive_item`
provenance nodes. Citation URLs up to 8,192 characters are preserved in full.
Longer URLs fail that library with a safe error instead of returning a partial
link. Names are bounded to 500 characters, parent paths to 2,000, content
types to 255, and timestamps to 100. The complete serialised result has a
768 KiB ceiling, including the full citation URLs.
Listing and search neither request nor return download annotations.

The folder presenter groups results by library and uses the shared DataTable
for file and folder labels, numeric byte sizes, modified times, citation links,
paths, and content types. It retains sorting, pagination, row details, copy,
and CSV export. Long text stays within cells. Only public item fields enter
table rows; references, provenance metadata, and internal fields are excluded.
Links use the shared HTTP URL guard. Empty and partial results retain their
own copy, and `has_more` remains visible even when a page has no eligible items.
Malformed result fields fall back to the default tool row.

`sharepoint_search_files` searches names, metadata, and indexed content through
Graph's [drive-root search](https://learn.microsoft.com/en-us/graph/api/driveitem-search).
The query must contain non-whitespace text and be 1-200 characters. Each
selected library returns `items` and `count`, with a default limit of 10 and
a maximum of 25 provider candidates over at most five pages. Remote, foreign,
unscoped, and package items are excluded, so counts can be below the limit.
Continuation URLs must retain the global Graph host and the original drive
search path as sent by HTTPX, preserving encoded path separators. The search
uses the same bounded metadata, provenance, citations, and complete result
ceiling as folder listing. It does not download content.
The search presenter echoes the query and groups matching items by library,
with a count for each library and explicit zero-match copy. It reuses the
folder item table and its public-field validation. Error entries retain their
copy alongside successful libraries. Malformed fields, inconsistent counts,
and pages above 25 items fall back to the default tool row.

All three read tools use the audited context runners and work in Code Mode. Known
references resolve by ID within exactly one selected drive, with at most 25
exact values per request. Larger requests fail before credentials or HTTP.
The listing tool's optional `folder` entity field authorises name lookup through
the conversation-scoped application API. Lookup requires a mounted tool,
conversation access, and actor-accessible compatible Active Context.
It searches selected drives and keeps case-insensitive name matches among the
bounded candidates, including files and folders. Choice descriptions identify
folders and explain that files cannot be used for folder listing.
Empty lookup text lists library roots. The field remains read-only in tool
presentation; an editable browser picker is pending separate UI work.
The resolver offers at most 25 choices across all libraries, with bounded local
choice paging. Ambiguous drive selections are skipped before credential access.
Link resolution and its result presenter are described below.

### File content

`sharepoint_read_file` takes a file reference and targets exactly one selected
library. Unselected or ambiguous drives fail before credentials or HTTP. The
item ID and parent drive must match the reference; remote shortcuts, folders,
and packages cannot be read. Supported types come from the shared file contract.
Images and other unsupported types report `unsupported_type`.

`SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES` defaults to 52,428,800 bytes (50 MiB) and
accepts 1-104,857,600 bytes. Metadata above the limit fails before download;
the same limit applies while streaming, even when metadata understates the size.
Both failures report `too_large`. Only `download_item` requests
`@microsoft.graph.downloadUrl` through `get_item`, consumes it through
`get_bytes`, and removes it from returned metadata. The URL is not persisted
or returned by the tool. Download metadata omits `$select` because SharePoint
can suppress the download annotation when selected metadata fields are present.
The response is still filtered to the explicit item fields and the one download
annotation before it reaches `download_item`. Ordinary metadata reads retain
`$select` and exclude download annotations. This follows Microsoft's
[pre-authenticated download contract](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content).

The result contains `name`, normalised `content_type`, actual downloaded
`size_bytes`, `modified_at`, `web_url`, `markdown`, `truncated`, and `source`
(`text` or `converted`). Provider text uses `sharepoint_drive_item` provenance
with `{drive_id}:{item_id}` as its source reference. Markdown is bounded to
64 KiB on a UTF-8 boundary, including the truncation marker. Citations retain
the full URL within the shared 8,192-character limit. Reads require a usable
HTTP(S) citation before downloading content. Missing or invalid citations fail
with safe metadata errors that omit the rejected value. Listing and search
retain optional citations. `truncated` records actual output bounding, so
complete content ending with the literal marker reports `false`.

Conversion uses the shared document helper with a 30-second deadline inside
the tool's 90-second timeout. Its cancellable AnyIO worker is killed on timeout
or cancellation, and bounds Markdown before returning it to the parent process.
AnyDoc retains its built-in decompression, nesting, node, and expansion limits.
No download URL enters the conversion worker. Text and HTML decode once inside
the worker with strict UTF-8 validation. Valid HTML returns `source="converted"`.
Invalid UTF-8 text or HTML, corrupt or encrypted documents, parser-limit
failures, and conversion deadlines report
`conversion_failed`, with copy explaining that the file may be protected or
damaged. The conversion helper's process deadline is opt-in; other callers
retain their existing thread execution.

The file-content presenter uses the shared read shell and sanitised Markdown
renderer. It shows the filename, content type, formatted size, and an
**Open in SharePoint** citation guarded by the shared HTTP URL validator.
Truncated content carries a **64 KiB limit reached** badge. Long content scrolls
within the result card. Provider error entries retain their recovery copy;
malformed display fields fall back to the default tool row. Only display fields
enter the view, excluding reference metadata and download annotations.

Metadata validation errors retain the owning operation: `search_files`,
`list_folder`, `get_item`, `read_file`, or `open_link`. Errors omit rejected
provider values.

`sharepoint_open_link` accepts an HTTPS SharePoint or work OneDrive URL up to
8,192 characters. A direct URL under a selected library resolves through
`/drives/{drive_id}/root:/{relative_path}`. Matching checks the hostname and
decoded path segments, chooses the longest library prefix, and rejects
traversal and encoded separators before credentials. Direct links target only
the matching connection. Library form and view routes ending in
`/Forms/*.aspx`, including `AllItems.aspx`, report `link_not_supported`
before credentials or HTTP and ask for a direct file or folder URL. The tool
does not extract item paths from their query parameters. Ordinary direct
file URLs retain benign query parameters such as `?web=1` during validation;
those parameters do not enter the Graph item path. Other `.aspx` item paths
remain eligible for direct resolution.

Missing or invalid cached library URLs are excluded from direct matching.
They cannot block a healthy library's direct link. Their drive IDs remain
selected for the sharing result's scope check. Other links use the
[Graph sharing endpoint](https://learn.microsoft.com/en-us/graph/api/shares-get)
once per selected connection, without a link-redemption header. Each connection
makes at most one logical metadata request, with the shared read retry policy.
Microsoft documents write permissions for that endpoint, but a tenant check
with only the existing read-only SharePoint grant successfully resolved an
already accessible file URL. Tenant policy and item permissions can still deny
a sharing link. No write scope is requested.

Link resolution checks every selected library on the resolving connection.
Only a local file or folder in that set returns a reference. A result from
another connection's selected drive is rejected. Remote shortcuts, packages,
ambiguous selections, and malformed metadata fail closed. A direct-path result
must also match the requested drive. Results use the same bounded item fields,
provenance, and citation limits as listing. Download annotations are excluded.

Successful results identify the actual library. A sharing request uses the
first selected library on that connection as its audit context, and records
the resolved `{drive_id}:{item_id}` in `external_ref`. Direct requests use the
matching library for both. Credential and provider failures remain audited
and isolated by connection through the shared context runner.

Failures report `not_found`, `access_denied` for a denied direct read,
`link_not_supported` for an invalid URL or denied sharing request, or
`library_not_selected`. The last includes bounded site and library names in
`data.library` as an untrusted node, derived from the returned site and file
URLs when available. Its recovery copy asks you to select that library in the
SharePoint connection and Active Context, refreshing discovery if needed.
Missing, invalid, or non-string optional site and file URLs retain generic
site/library hints and the `library_not_selected` error code.
Keeping the hint as a node preserves Code Mode provenance on failure. A denied
sharing request asks for the file's direct URL.

The link presenter shows each resolved file or folder through the shared item
table, including its guarded citation. Failed entries retain their recovery
copy and show the site/library hint as escaped plain text for
`library_not_selected`. Missing or malformed hints leave the recovery copy
visible. The pasted URL appears as plain text in the card summary and details;
it is never activated as a link. Malformed resolved items fall back to the
default tool row. References, provenance metadata, and download annotations
are excluded from the view.

Fetching original Office files into Files, editing them, and saving them back
to SharePoint is pending. Markdown reads do not provide that workflow.

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
