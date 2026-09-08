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
and `sharepoint_drive` resources, respectively. Agent tools are pending.

## Frontend contracts

The three Microsoft modules contribute isolated logos, catalogue descriptions,
and shared administrator setup and removal guidance. Tool presenters are
pending alongside agent tools.

## Operator setup

Follow the [Microsoft Entra app registration guide](../../guides/microsoft-entra-app-registration.md).
