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
and `sharepoint_drive` resources, respectively.
The seam's `time.py` parses local date-times without offsets, accepts IANA or
Windows zone names, bounds windows, and builds `dateTimeTimeZone` values.
`people.py::search_people` frames each person field as an `outlook_person`
node for both Outlook packages. `graph_client_for_principal` builds the
client each package's tools and pickers use to act as the user for one
selected resource.

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

Outlook Calendar cards use the provider-neutral calendar kit in
`src/components/tool-ui/calendar/`, which Google Calendar can reuse.
`CalendarEventList` groups events by local day and shows each event's time
zone; `CalendarSlotList` lists free or busy slots the same way. Times are
wall-clock values in a named zone, so the kit formats them without converting
to the browser's zone. `CalendarEventDraft` describes the event a write sets,
with null for what an update leaves alone. Event lists, the event view,
availability, meeting times, people, and each write have a registered
presenter.

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
  returns one window of up to 64 KiB of converted Markdown from `offset`
  (default 0). While `truncated` is true, the result's `hint` names the next
  `end_offset`. Embedded items, reference attachments, images, unsupported
  types, and oversized files fail closed.
- `outlook_mail_find_in_attachment` takes the same reference, a literal query
  of up to 200 characters, and a limit of up to 25. It searches the whole
  converted attachment case-insensitively and returns excerpts with byte
  offsets that `outlook_mail_read_attachment` accepts.
- `outlook_mail_save_attachment` saves the original bytes of one scoped file
  attachment as a new workspace File. See [Saving attachments to
  Files](#saving-attachments-to-files).
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
Attachment reads and finds convert the whole attachment on every call and
window or search it in the document worker, as `sharepoint_read_file` and
`sharepoint_find_in_file` do; the card shows which part of the text it holds.
An offset that is beyond the text or inside a UTF-8 character fails with
`invalid_offset`. Unlike SharePoint, which writes files back and decodes
strictly, text and HTML attachments keep replacement decoding for invalid UTF-8
bytes, so a Latin-1 attachment stays readable.
The `outlook_message` preview returns raw content to the engine for bounding
and sanitisation. Preview definitions validate provider-specific reference
patterns: Outlook permits bounded base64 IDs; Gmail retains its short URL-safe
IDs.

### Saving attachments to Files

`outlook_mail_save_attachment` takes one `OutlookAttachmentReference` and an
optional `folder` name with `write_file` folder semantics. It mirrors
`sharepoint_copy_to_files`: it requires only the mailbox read binding, uses
`provider_query` egress, and is an internal write that is automatic by
default with approval supported. It works in Code Mode. No OAuth scope is
added.

`operations/download_attachment.py` owns the metadata check and the bounded
raw download that both the read and save paths use. The save path
(`operations/copy_attachment.py`) never calls the Markdown converter, so
images and other Files types that cannot be read as text still save. Before
downloading, it rejects:

| Case | Error code |
| --- | --- |
| Embedded email or linked attachment | `unsupported_attachment_kind` |
| Type that the Files contract does not accept, including `application/octet-stream` | `unsupported_attachment_type` |
| File name extension that does not belong to the declared type | `attachment_type_mismatch` |
| Declared size over the limit | `attachment_too_large` |

The limit is the smaller of `OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES` and the Files
category limit. Streamed bytes enforce the same limit when `Content-Length` is
absent or understated. A name without an extension takes the type's
extension.

The bytes go to `services/integrations/files/create_copy.py` inside the
caller's savepoint. The File, its first revision, the conversation link, and
the success audit commit together; a storage failure or interrupted worker
leaves no File. A call dispatched again after commit, or a second explicit
save, creates another copy. Storage writes are never retried because the Graph
read retried. Audit evidence records the mailbox, message, and attachment IDs
with the File and revision IDs, never bytes or provider bodies. The result
returns the File reference, file and revision IDs, the saved name as an
`outlook_message` node, the Files content type, the size, and the source
attachment reference. The card shows the saved File with an **Open in Files**
link, and plays saved images, video, and audio in place; failures show the
error message from the table above.

### View and save attachments from the message card

Each file attachment on the `outlook_mail_read_message` card, and the
`outlook_mail_read_attachment` card, has **View** and **Save to Files**;
clicking the attachment name also views it. Both call a route directly. They
send no message, start no agent turn, and agent tool policies don't apply.

- `POST /api/v1/integrations/conversations/{conversation_id}/file-views`
  returns the attachment's bytes for that view only. Nothing is stored. The
  response carries `Content-Security-Policy: sandbox; default-src 'none'`,
  `nosniff`, and `no-store`. Only images, video, audio, and PDF are viewable;
  other types fail with `unviewable_file_type` and a prompt to save to Files.
  It needs a role that can read the workspace. Successful views are not
  audited, as with previews; failures are.
- `POST .../file-saves` saves the attachment as a File with the person as
  revision actor, links it to the conversation, and writes a user-actor
  `file` create audit event (operation, conversation, revision, and source
  reference identity; no bytes or connection IDs) in the same commit. It needs
  a role that can write Files, so a read-only member is refused before
  credentials. A failure rolls back and records a failure audit with the
  operation, source identity, and error code.

Both take `{provider_key, reference}`, where `reference` is the scoped entity
reference from the tool result. The routes are provider-neutral: a provider
registers an `IntegrationFileSourceDefinition` (entity kind, reference model,
operation, and a bounded `download`) in its plugin's
`file_source_definitions`. Outlook's is in
`integrations/outlook_mail/file_sources.py` and runs `copy_attachment`, so the
pre-download checks and limits above apply. `services/integrations/file_sources/`
validates the reference with the provider's model and resolves the
conversation's active context with `resolve_conversation_target`, the check
the conversation preview route also uses. Exactly one target must match the
reference's mailbox, so another person's conversation, or a mailbox not
selected in it, fails before credentials. The download uses the person's own
connection credential.

In the browser, images, video, and audio open in a dialog from a blob URL that
is revoked when the dialog closes. PDFs open in a new isolated tab from a
blob URL revoked after a minute. The actions are hidden on shared transcripts.
Inline images, which are usually signature logos, collapse under **Show N
Inline Images**. A saved row shows **Open in Files**, and the row and its
viewer share that state, so a save from the viewer also marks the row. Saved
state lasts for the
page view, so a save after a reload makes another copy, as a repeated agent
save does. The agent learns about a card view or save only if the operator
mentions it.

## Outlook Calendar reads

Select one or more Outlook calendars in Active Context to use these tools:

- `outlook_calendar_list_events` lists events that overlap a local `start`
  and `end` window in each selected calendar, including each occurrence of a
  recurring series, with up to 100 events per calendar. The window can be at
  most `OUTLOOK_CALENDAR_MAX_RANGE_DAYS` long (default 62).
- `outlook_calendar_read_event` targets one scoped event reference and adds
  up to 20,000 body characters, 100 attendees with their responses, and a
  recurrence summary.
- `outlook_calendar_get_availability` returns free and busy periods, working
  hours, and Graph's `availabilityView` for up to 20 addresses over at most
  31 days. Event subjects are omitted.
- `outlook_calendar_find_meeting_times` asks Graph for up to 10 suggestions
  for up to 20 required attendees, a 5 to 480 minute duration, and a window
  of at most 14 days, using working or personal hours.
- `outlook_calendar_search_people` resolves a name to up to 25 people, like
  `outlook_mail_search_people`.

Times are ISO 8601 strings without an offset plus a `time_zone`. When the
agent omits `time_zone`, the tool uses the calendar's recorded mailbox zone
and returns it with the result; an unusable recorded zone falls back to UTC.
Requests send `Prefer: outlook.timezone` so Graph returns times in that zone.
`calendarView` reads offset-less bounds as UTC and Windows zone names have no
local offset table, so the listing pads the request by the widest UTC offsets
and keeps events that overlap the window in local time.

Event reads fan out across the selected calendars. Availability, meeting
times, and people search run once per connection, against its first selected
calendar. Private and confidential events show "Private appointment" with no
location or body unless discovery recorded that the calendar can view private
items. Provider text uses `outlook_event` or `outlook_person` nodes, event
references carry a fixed label, and the complete result has a 768 KiB limit.
The event picker searches the next 30 days of each unambiguous selected
calendar by subject. It matches the subject it shows, so a search can't
confirm a masked one, and it marks a series master "Whole series" so an
approver can tell a change to every occurrence from a change to one. Bad
windows, zones, and address lists return a retry message to the model before
any Graph request.

## Outlook Calendar writes

Four tools change a calendar. Each needs approval every time
(`supports_auto=False`), because invitations, updates, and cancellations reach
real people:

- `outlook_calendar_create_event` creates a single event in one calendar and
  sends an invitation to every attendee. `calendar` picks the calendar; when
  it is omitted the tool uses the only writable selected calendar, else the
  default one, else asks the model to choose. `is_online_meeting` adds a Teams
  link.
- `outlook_calendar_update_event` patches the subject, times, attendees,
  description, or location of one event and sends attendees an update.
  `attendees` replaces the whole list, and `start` and `end` move together.
  On an occurrence or series master it changes only the listed fields, never
  the recurrence; moving an occurrence past a neighbour fails with
  `occurrence_boundary`.
- `outlook_calendar_respond_to_event` accepts, tentatively accepts, or
  declines an invitation, optionally without telling the organiser.
- `outlook_calendar_cancel_event` reads the event first. An organiser's
  meeting with attendees is cancelled, which sends the comment to each
  attendee; an event without attendees is deleted. An attendee's event fails
  with `not_organizer` before any change, pointing the model to a decline.

No write fans out. The event reference's `calendar_id` selects the calendar,
which must be a selected calendar the connection can edit. The approval shows
the calendar and time zone the write falls back to, and the tool sends those
approved defaults (`approved_display_args`) rather than recomputing them, so
the attendees, times, and zone the approver saw are what Graph receives.
`_calendar_choice` in the display arguments tells the card to hide the
calendar picker when only one writable calendar is selected.

Creates carry a `transactionId` derived from the run and tool call, so a
repeated run of the same approved call can't create a second event. Pending
audit detail records counts, times, zone, response, action, and the
transaction ID, never subjects, bodies, or attendee addresses; the terminal
`external_ref` is the event ID. A timeout after dispatch records
`unverified`, and the result tells the model to check the calendar before
trying again.

Each write has its own result card on the shared outcome layout with calendar
icons. The create approval puts Start, End, and Time Zone on one row and
edits Teams Meeting, All Day, and Show As on one line with the calendar kit's
`CalendarEventOptions`.

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

All five read tools use the audited context runners and work in Code Mode. Known
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
Both failures report `too_large`. The shared `download_utils` helper serves
`download_item` and `copy_item`. It requests `@microsoft.graph.downloadUrl`
through `get_item`, consumes it through `get_bytes`, and removes it from
returned metadata. The URL is not persisted or returned by the tool.
Download metadata omits `$select` because SharePoint
can suppress the download annotation when selected metadata fields are present.
The response is still filtered to the explicit item fields and the one download
annotation before it reaches the download helper. Ordinary metadata reads retain
`$select` and exclude download annotations. This follows Microsoft's
[pre-authenticated download contract](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content).

`sharepoint_read_file` accepts a UTF-8 byte `offset` (default zero) and
`max_bytes` (4-65,536, default 65,536). Its result contains `name`, normalised
`content_type`, downloaded `size_bytes`, `modified_at`, `web_url`, `markdown`,
`offset`, `end_offset`, `total_bytes`, `truncated`, `limit_reached`, `version`, and `source`
(`text` or `converted`). `truncated` means more content follows this window.
The continuation `hint` names the next offset and the find tool. An offset
past the total or inside a character reports `invalid_offset` with the total.
The shared `utils/text_window.py` helper preserves native file-read boundaries.

Reads cover the whole converted document. The worker returns only the requested
window, bounded to 64 KiB on UTF-8 boundaries. `total_bytes` counts the complete
Markdown, and `limit_reached` is false. No conversion marker replaces later
content. Each window downloads and converts the file again as a separate
audited read; converted documents are not cached. Use find to reach relevant
content with fewer reads than sequential paging. Offsets refer to that conversion;
a provider edit between calls can change the content at an offset.

`sharepoint_find_in_file` takes the same scoped file reference, a literal query
of 1-200 characters, and a match limit of 1-25 (default 10). It searches the
whole converted document inside the worker, including content beyond 2 MiB.
Matching is case-insensitive and escapes regex metacharacters. The worker
collects at most one extra match to set `has_more`. Each match returns an
excerpt with up to 120 characters either side and its starting UTF-8 byte
`offset`. Pass that offset to `sharepoint_read_file` for surrounding content.
The result also contains `name`, `web_url`, `total_bytes`, `limit_reached=false`,
and `count`. Byte offsets are accumulated without re-encoding every prefix.
Only bounded excerpts leave the worker, rather than the complete Markdown.

Provider text, including windows and excerpts, uses `sharepoint_drive_item`
provenance with `{drive_id}:{item_id}` as its source reference. Citations retain
the full URL within the shared 8,192-character limit. Reads and find require a
usable HTTP(S) citation before downloading content. Missing or invalid citations
fail with safe metadata errors that omit the rejected value. Listing and search
retain optional citations. A literal truncation marker in source text has no
special meaning for window or search coverage.

The internal bulk conversion operation `convert_item` returns plain Markdown
bounded by `SHAREPOINT_FILE_MAX_MARKDOWN_BYTES`: default 2,097,152 bytes, range
65,536-10,485,760. It reports `limit_reached` and includes the shared marker when
capped. A caller can supply its own `max_bytes`. This bulk-output cap prepares
the conversion seam for Knowledge Base import, which remains pending. It does
not limit whole-document windows or find.

Conversion uses the shared document helper, which runs in the document worker
pool with the `DOCUMENT_TOOLS_TIMEOUT_SECONDS` deadline (60 seconds by default)
inside the tool's 90-second timeout. The worker is killed on timeout,
cancellation, or its memory limit. Conversion, windowing, and matching all run inside the deadline;
only bounded Markdown, a window, or excerpts return to the parent process.
AnyDoc retains its built-in decompression, nesting, node, and expansion limits.
No download URL enters the conversion worker. Text and HTML decode once inside
the worker with strict UTF-8 validation. Valid HTML returns `source="converted"`.
Invalid UTF-8 text or HTML, corrupt or encrypted documents, parser-limit
failures, and conversion deadlines report
`conversion_failed`, with copy explaining that the file may be protected or
damaged.

The file-content presenter uses the shared read shell and sanitised Markdown
renderer. It shows the filename, content type, formatted size, and an
**Open in SharePoint** citation guarded by the shared HTTP URL validator.
Partial windows show their size and position using the shared byte formatter.
A **More content available** badge means another window follows. Retained
capped results show **Conversion limit reached** independently. Complete
files omit the position line. Long content scrolls within the result card.

The find presenter echoes the literal query and shows the filename, guarded
citation, and match count. It distinguishes no matches from a bounded first
set of matches. Excerpts render as escaped plain text with the first matching
phrase emphasised case-insensitively. Whole-document results show no conversion
limit notice, including for matches beyond 2 MiB. Retained capped searches
show **Conversion limit reached** without assuming a fixed size limit.

Both views preserve provider recovery copy and fall back to the default tool
row for malformed display fields. Only display fields enter the views;
reference metadata, download annotations, and model continuation hints stay
out. Raw byte offsets do not appear in operator copy.

Metadata validation errors retain the owning operation: `search_files`,
`list_folder`, `get_item`, `read_file`, `find_in_file`, or `open_link`.
Shared file validation, download, and conversion errors use the caller's
`read_file` or `find_in_file` context. Bulk conversion retains `read_file`.
Metadata lookup failures retain `get_item`, including within reads and finds.
Errors omit rejected provider values.

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
a sharing link. Link resolution requests no additional write scope. The
connection grant includes the write permissions described below.

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

The backend tools support copying original Office files into Files, editing
them with the document tools, and saving an approved replacement to SharePoint.
Source approval cards and copy results use the shared presenters. Manual Office format
preservation and live tenant behaviour remain unverified.

## SharePoint writes

Select a writable library in Active Context to use these approval-gated tools:

- `sharepoint_create_folder` creates a folder under an optional parent folder.
- `sharepoint_write_file` saves text or a workspace File as a new file in an
  optional folder.
- `sharepoint_update_file` replaces a file using its reference and the
  `version` returned by `sharepoint_read_file` or `sharepoint_copy_to_files`
  as `expected_version`.

Each tool targets one library and works through direct calls and Code Mode.
Without a folder reference, exactly one writable library must be selected.
References must belong to an unambiguous selected drive. Read-only resources
produce the shared write-denial audit before credentials or provider requests.
Automatic execution is unavailable. The three write presenters use the shared
approval and outcome cards. The server declares editable name, destination,
and multiline text fields, and keeps the replacement file and version locked.
Approval cards identify the reviewed library and show its root as the default
when no folder is chosen. **Add Folder** opens the destination picker for a
root proposal. Clearing an optional folder returns to the reviewed root.
An edited folder can select another library. Root execution still requires
one unambiguous writable library matching the reviewed target. If clearing a
folder cannot preserve that target, prepare a fresh proposal.
The library label remains plain text, separate from replayable arguments.

Approval cards use the existing conversation-scoped lookup to show the
selected item, library, and path. Lookups reuse the entity editor query cache.
SharePoint destination fields declare no sibling dependencies, so name and
content edits send no lookup requests and stay out of lookup cache keys.
Choice descriptions include a path relative to the library, bounded to 1,000
characters with an ellipsis when shortened. A pending or unavailable path has
explicit copy. An edited folder in another library replaces the original
library label with a selected-item description until lookup completes.
The shared entity editor verifies the selected destination.
Name validation mirrors the server's character, length, and reserved-name
rules. Empty text, invalid Unicode, and prohibited control characters block
approval with a correction message. HTML and Markdown remain escaped text
in the multiline editor. Replacement cards identify the file and explain
that SharePoint keeps its previous version.

Outcome cards show the public item name, parent location relative to the
library, byte size, and an **Open in SharePoint** link through the shared HTTP
URL guard. Root locations say **Library root**. Missing or unrecognised paths
say **Location unavailable**. Graph routing prefixes and drive IDs stay out
of these locations, including unverified outcomes. Version conflicts, name
conflicts, locks, quota failures, expired sessions, invalid upload ranges,
unsupported types, and size limits have recovery copy. Unverified outcomes
remain unconfirmed and ask you to check the library before trying again.
Private references, upload and download fields, versions, and provenance
metadata stay out of the outcome view. Malformed results fall back to the
default tool row. The module registers five read and three write presenters.

The existing SharePoint connection requests delegated `Files.ReadWrite.All`
and `Sites.ReadWrite.All` alongside its read scopes. Grant administrator consent
before deploying the expanded manifest, then reconnect and refresh discovery.
Both granted write scopes are required for a drive to be writable. Connections
with only the read grant retain their read tools. The signed-in person's
SharePoint permissions still bound access.

Names are 1-255 characters and reject SharePoint's reserved names, path
separators, control characters, and leading or trailing spaces or dots.
A name conflict reports `name_exists`; creation never renames or replaces an
existing item. Text must be non-empty, contain valid UTF-8, and contain no
control characters except newline and tab. The shared file contract selects
text types by extension and rejects Office files as text destinations.
Text replacements also use its normalised MIME lookup and editable flag. Invalid
or unsupported provider MIME values fail before pending intent.
`FILES_MAX_TEXT_EDIT_BYTES` bounds the UTF-8 text at 2 MiB by default.
`SHAREPOINT_FILE_MAX_UPLOAD_BYTES` separately defaults to 50 MiB and accepts
1-262,144,000 bytes.

Every file write uses an upload session, including small text files. Replacement
preparation reads the scoped metadata and checks the reviewed `eTag` before
pending intent. Execution checks it again and sends `If-Match` when creating
the session. A mismatch reports `version_conflict` and asks for a fresh read.
The version is a bounded opaque token; pass it unchanged. Invalid session
responses and replacement metadata fail as undispatched content mutations.
Failures after a possible commit retain an unverified outcome.

The shared Graph client consumes signed upload URLs with `upload_fragment`,
`upload_status`, and `cancel_upload`. It pins public DNS addresses, strips
inherited bearer tokens and cookies, refuses redirects, suppresses HTTP
logging for the task, and retains no signed URLs in errors or public results.
Fragments are sequential and at most 10 MiB. A failed non-final fragment can
resume from the server's expected offset at most three times, after cancellable
delays of one, two, and four seconds. A failed upload before the final fragment
attempts to cancel its session. Cancellation during
the final fragment retains an uncertain outcome and is never replayed.

Committed files are checked against their byte count and locally computed
QuickXorHash. Missing or mismatched evidence reports `unverified_mutation`.
An ambiguous final response triggers one session-status read and one scoped
metadata read. A final upload response acknowledging the committed item is
required to attribute a write to this attempt. Missing ranges mean the session
is incomplete. A missing session can mean completion or expiry, and a failed
status lookup provides no commit evidence. Matching destination size and hash,
even with a changed version, cannot distinguish this upload from another
writer. An unchanged replacement version also cannot confirm a replacement.
All lost-response reconciliation outcomes therefore remain
`unverified_mutation`, including a disappeared session with matching content.
Validated metadata and a single off-thread hash comparison retain observations
for inspection, without marking a commit or claiming unacknowledged bytes.
The final fragment is never replayed.
Session expiry reports `upload_session_expired`; a `409 nameAlreadyExists`
response reports `name_exists`. Other 409 responses retain a generic rejection.
A version conflict reports `version_conflict`, a lock reports `locked`, and
exhausted storage reports `quota_exceeded`.

Pending intent contains the library, action, byte count, content type, and
expected version, excluding file names and text. Terminal evidence retains
the item reference, versions before and after, transfer progress, commit state,
and hash verification. Reconciliation also records whether session status is
incomplete, missing, unavailable, or unknown. Provider metadata in results
retains untrusted framing.
The shared `write_lifecycle.py` helper handles preparation, execution, and
cancellation for SharePoint and Outlook; provider callbacks build their own
evidence while the existing audit runner owns persistence.

Direct and Code Mode calls return uncertain writes as `unverified_mutation`
entries with correlated terminal operation evidence. The invocation completes
and the run can continue. This completion does not confirm the external write.
Another write requires a fresh approval; automatic mutation replay is forbidden.

Live tenant qualification of conditional sessions, commit conflicts, hashes,
and completed-session status remains unverified. The maintainer waived that
implementation prerequisite on 17 September 2026.

### Workspace File sources and copies

The write and replace tools accept exactly one of `content` or `source`.
`content` retains the text-only rules. `source` is a core `FileReference`
resolved through workspace visibility and immutable revision storage. Sources
must belong to the active workspace; copy a platform File into the workspace
before using it. The file contract validates the source type and extension,
and empty or oversized sources fail before storage or SharePoint access.
A new name must match the source type. A replacement must retain the remote
file's MIME type;
a mismatch reports `type_mismatch` before pending intent or upload.

Approval display evidence retains the File name, type, size, and the exact
`file_id`, `revision_id`, and `content_hash`. Execution checks the retained pin
against the current visible revision before resolving SharePoint credentials.
A missing or changed pin reports `source_changed`; missing or inaccessible
Files report `source_unavailable`. The shared storage reader checks metadata,
bounds streamed bytes by the retained revision size, and verifies SHA-256.
Contradictory bytes report `source_changed`. Approval cards show the reviewed
File name, type, and size and use the existing workspace File picker.
Choose exactly one of text content or a File. After changing the File, click
**Review selected File**, check the refreshed details, then approve. This
explicit review also lets you select the latest revision of the same File.
Switching to text clears the File selection. HTML and Markdown text stay escaped.

The review endpoint retains canonical executable arguments separately from the
original model call and stores the source revision in server-owned display
evidence. It locks the run family, checks the actor, workspace, pending leaf,
approval revision, and original expiry, then refreshes the proposal. Direct,
Code Mode, and delegated approvals use the same path. An older proposal or an
unreviewed File selection cannot resume. Execution never accepts a source pin
from replay arguments or recomputes the approved pin.

`sharepoint_copy_to_files` downloads original bytes from one selected library
and saves a new workspace File. It requires only the read binding, uses
`provider_query` egress, and follows the native File write policy: automatic
by default, with approval supported. Run envelopes and tool policies still
apply through dispatch. Copying is an internal write and grants no SharePoint
write permission. All file-contract types are accepted, including images and
video. Both metadata and streamed bytes are bounded by the smaller of the
SharePoint download cap and the file category limit. Downloaded bytes must
match the exact source size and any supplied QuickXorHash or SHA-1 digest.
Missing optional hashes are accepted. Contradictory content reports
`source_changed` before any local reservation, folder, File, or link is created.

An optional `folder` names a workspace Files folder and creates it when absent.
The copy uses an agent revision actor, links the File to the conversation,
and returns its typed reference, revision, size, type, and source `version`.
Audit evidence retains the drive/item source, `eTag`, File ID, and revision ID.
Names and citations retain SharePoint provenance; bytes and signed URLs never
enter tool output. Copied Files use ordinary workspace visibility, retention,
and immutable revision rules. The copy card shows the source item with a
guarded **Open in SharePoint** citation and the saved File with an **Open in
Files** link, name, type, and size. Failed copies show recovery guidance.
Malformed results use the default row; private revision evidence and signed
URLs remain excluded from the card.

Before writing bytes, the copy reserves its destination in an independent
tenant transaction. The caller locks that reservation through storage writes
and final commit. Cancellation waits for the provider write to settle before
releasing the lock. Rollback leaves the reservation for expiry cleanup; failed
deletion retains it for another sweep. The File, consumed reservation, and
operation success audit commit together, so a lost commit response cannot
expose a committed copy to cleanup. Invocation completion follows that commit.

To edit and save an Office document:

1. Call `sharepoint_copy_to_files` with the selected document reference.
2. Edit the returned File with `edit_presentation`, `edit_workbook`, or
   `edit_word_document`. Each edit appends a revision to that File; the
   SharePoint document remains unchanged.
3. Call `sharepoint_update_file` with the original SharePoint reference,
   the copied `version` as `expected_version`, and the edited File as `source`.
4. Review and approve the replacement. Check the returned outcome and citation.
   A version conflict requires a fresh copy or read and another review.
   An unverified outcome requires checking SharePoint before another save.

Failed saves retain the edited workspace revision. Fixture scenarios verify
original-byte copying, revision editing, exact uploaded bytes, local and remote
conflicts, and ambiguous commits through direct tools and Code Mode. The
maintainer performs manual deck/workbook editing and Office checks separately;
format preservation and live tenant behaviour remain unverified here.

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

The four sending tools check the workspace
[Do Not Email](../../architecture/governance.md#do-not-email) list before
Graph's send request. Send message checks its arguments before it creates the
draft. Reply and forward read the draft's To, Cc, and Bcc back from Graph
after creating it, because Graph fills in a reply's recipients; recipients
that can't be read stop the send. Send draft checks the draft it already read.
A listed recipient refuses the whole send with `error_code` `do_not_email`
and a detail that names the address. Any draft created is left unsent and
returned in the result. Send message, forward, and send draft also list
listed recipients in their approval display under `_do_not_email`, and the
card blocks approval while any of them is still a recipient.

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

### Mail merge sends

Mail merges send from the background `mail_merge.send` job, not from an agent
tool, through `operations/send_merge_message.py`. The sender reuses
`create_draft` and `send_message` with one To address:

- The draft's immutable ID and its `internetMessageId` are committed before
  the send request. `MailWriteState` keeps the `internetMessageId` that Graph
  returns when it creates the draft, and the sent copy keeps it.
- After a crash, reconcile reads the stored draft ID, which follows the email
  into Sent Items. `isDraft` true means not sent, false means sent, and a
  missing item means Couldn't Confirm. It never searches.
- The merge client is built with `send_errors=True`. Graph processes no
  throttled request, so every `429` becomes a `REJECTED`
  `IntegrationRateLimitError` with Graph's `Retry-After`, and
  `ErrorExceededMessageLimit` becomes `IntegrationSendingLimitError`. Other
  Outlook tools keep the shared mapping.

Exchange Online usually reports a mailbox over its daily limit as a bounce
after a `202`, not as an error. The mail merge sending budget is what keeps a
mailbox under its limit. See [Mail merge](../mail-merge.md).

## Operator setup

Follow the [Microsoft Entra app registration guide](../../guides/microsoft-entra-app-registration.md).
