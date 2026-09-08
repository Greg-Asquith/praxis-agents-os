# Google Analytics implementation

Read this when changing Google Analytics connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/google_analytics/)
and [frontend module](../../../apps/web/src/integrations/google_analytics/index.ts).

## Backend contracts

Google Analytics contributes workspace OAuth and service-account connection,
a bearer-only Data/Admin REST client, and bounded Admin API discovery of
read-only GA4 properties. Its five code-eligible read tools discover bounded
standard/custom report fields, check which candidate fields can be added to a
compatible standard report, and run structured standard or realtime reports
with local request validation, header-typed metric values, and the shared
report row bound, and list the Google Ads accounts linked to each selected
property without exposing link creator email addresses. Standard reports also
expose access-restriction and sampling metadata. Accounts remain property
metadata, and discovery must not add per-property enrichment calls. Its OAuth
settings stay in the provider package
and use a Google Cloud client isolated from every other Google service.

## Frontend contracts

Google Analytics contributes its logo, catalogue description,
connection guidance, and guarded report, realtime, report-field,
compatibility, and linked-Google-Ads-account presenters over the shared
fan-out and table kits.
