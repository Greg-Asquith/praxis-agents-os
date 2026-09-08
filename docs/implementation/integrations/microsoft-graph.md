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
Gmail. Both use the shared `provider-content-preview.tsx` loader. Gmail retains
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
IDs. Sending, replying, forwarding, drafting, moving, and updating
messages remain pending.

## Operator setup

Follow the [Microsoft Entra app registration guide](../../guides/microsoft-entra-app-registration.md).
