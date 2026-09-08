# Notion implementation

Read this when changing Notion connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/notion/)
and [frontend module](../../../apps/web/src/integrations/notion/index.ts).

## Backend contracts

Notion contributes a personal public OAuth grant, a versioned REST client,
provider-owned token and live identity resolution, and one stable workspace
resource. Its authorisation picker controls page access. Three code-eligible
read tools search shared page and data-source titles, read bounded enhanced
Markdown, and query bounded data-source records through scoped Active
Context references. Opaque search continuations bind to the active Notion
workspace that issued them. Per-connection process pacing complements
provider retry handling. Data-source records cap compact properties at 24 KiB
each and report omitted properties; every complete Notion tool result must fit
within a 768 KiB serialised UTF-8 budget. Provider-authored content stays
untrusted.

### Approved writes

Three code-eligible Notion write tools create pages, replace exact text, and update
schema-validated scalar properties. They are approval-only, require a
writable Active Context resource, reload live target and schema state during
preparation, use non-retried mutation requests, and close every intent as
applied, failed, or unverified.

For Knowledge Base imports and refresh, read
[Knowledge sources](../knowledge-sources.md).

## Frontend contracts

Notion contributes its logo, catalogue
description, personal-authorisation guidance, and separate search, page-read,
data-source-query, and approval-gated write presenters over the shared
approval, fan-out, records-editor, and Markdown surfaces.
