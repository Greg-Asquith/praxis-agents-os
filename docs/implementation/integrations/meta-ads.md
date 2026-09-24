# Meta Ads integration

Meta Ads connects a workspace to the ad accounts assigned to an agency's Meta
system user. Discovered accounts can join active context and Context Groups.
Agent tools, Facebook sign-in, and event delivery are pending.

Backend code lives in `apps/api/integrations/meta_ads/`; the web module lives in
`apps/web/src/integrations/meta_ads/`. The provider uses the shared API-key
connection and secret-reference path with a field labelled **Access token**.
Connections belong to the workspace, not an individual user.

## Set up the agency's app

Use one agency-owned app for each deployment. Complete this setup in Meta:

1. In the agency's business portfolio, create a Meta app and add the Marketing
   API product. Record its mode and permission access levels.
2. Have each client share its ad account and Page with the agency's business
   portfolio as a partner.
3. In **Business Settings > Users > System users**, create or select a system
   user and assign the accounts. Grant **Manage campaigns** for management or
   **View performance** for reporting. Assign **Advertise** on the Pages.
4. Generate a System User access token for the agency's app. Select **Never**
   for expiry and request the permissions listed below.
5. In the deployment, add `meta_ads` to `INTEGRATIONS_ENABLED_PROVIDERS`.
6. In Praxis **Integrations**, connect Meta Ads and paste the token into
   **Access token**. Select the discovered accounts for the intended context.

The setup requests these permissions:

| Permission | Intended use |
| --- | --- |
| `ads_read` | Ad account reporting |
| `ads_management` | Ad account management; required for writable discovery |
| `business_management` | Business asset access |
| `pages_show_list` | Page discovery for later ad workflows |
| `pages_manage_ads` | Page advertising for later ad workflows |
| `pages_read_engagement` | Page data for later ad workflows |

Page resources and agent operations remain pending. An empty discovery result
is valid: assign accounts to the system user, then select **Rediscover**.
Adding accounts does not require replacing the token if its permissions remain
sufficient. The connection label is the label entered in Praxis.

The intended agency setup uses a development-mode app with standard permission
access. Partner-account and Page access without App Review or Business
Verification is an accepted implementation assumption, not a verified result.
If the agency's app cannot use its partner assets, revisit this setup before
relying on it. Personal user tokens and token renewal are unsupported.

## Configure app-secret proof

`META_ADS_APP_ID` is optional deployment metadata. `META_ADS_APP_SECRET` is
optional; unset and blank values both disable proof generation. Store the
agency's app secret in the deployment's secret store and enable **Require App
Secret** in that same Meta app when using this protection.

For every request with a non-empty secret, the client computes
`appsecret_proof` as hex-encoded HMAC-SHA256 of the resolved access token,
using the app secret as the key. Tokens travel only in the bearer header.
Proofs travel in the query string, so provider HTTP diagnostics are suppressed
and error details exclude raw provider text. Discovery and credential-based
client helpers use the same deployment secret.

All pasted tokens must come from that agency app. A Graph error mentioning
`appsecret_proof` produces guidance to use the agency's app when a secret is
configured, or to ask the administrator to add the secret when absent. Exact
live error bodies and subcodes remain unverified; generic permission errors
do not establish an app mismatch.

## Discovery and writability

Discovery reads `/me` for identity, `/me/permissions` for granted permissions,
and `/me/adaccounts` for account data and `user_tasks`. Missing identity fails
with guidance to replace the token. Account discovery requests 100 records per
page, with a 20-page cap. A cap or repeated cursor retains discovered accounts
and marks the connection degraded with `page_cap`.

Pagination accepts only HTTPS URLs on `graph.facebook.com` with the same
versioned path. The client extracts the next cursor and rebuilds the request
with its own bearer token and proof; it does not forward the supplied URL.

Each `meta_ads_ad_account` resource uses its bare numeric account ID. Discovery
deduplicates by ID, sorts by name, and falls back to `Ad account ID`, with the
account ID substituted, when a name is absent. Metadata includes currency,
time zone, the account status label, business ID and name, tasks, and granted
token permissions.

An account is writable only when all these conditions hold:

- Account status is `ACTIVE` (`1`).
- The token has granted `ads_management` permission.
- Account tasks include `MANAGE` or `ADVERTISE`.

Closed (`101`) and pending-closure (`100`) accounts are omitted. Other accounts,
including disabled, unsettled, or unknown statuses, remain read-only. Missing
tasks also keep the account read-only. Rediscovery refreshes these permissions.
The provider declares no OAuth scope requirement: the pasted credential does
not contain an OAuth grant. Write bindings require a writable resource through
the shared active-context resolver.

## Errors and request limits

Provider errors follow the existing integration exceptions and retry policy:

| Graph code | Treatment |
| --- | --- |
| `190` | Authentication failure; replace the expired or revoked token |
| `10`, `200`-`299` | Permission failure; check token grants and asset assignments |
| `4`, `17`, `32`, `613`, `80000`-`80014` | Rate limit; use the shared bounded retry path |
| `1`, `2`, or `is_transient=true` | Transient failure; use the shared bounded retry path |
| `100` and other Graph errors | Validation failure |

Details retain a bounded, validated `fbtrace_id` for support without copying
the provider's error message. Numeric business-use-case usage counters can
appear in debug logs. Usage-based pacing is pending.

The Marketing API access tier is separate from permission access. In the
agency's App Dashboard, check the Marketing API access tier. If it is
**Limited access**, use the dashboard's **Full access** request flow after
building successful API usage and complete the prerequisites Meta displays.
The initial tier and exact request prerequisites remain unverified for the
agency's app. Do not treat the permission level as evidence of a rate limit.

## Version upgrades

`META_GRAPH_API_VERSION` in `client.py` pins requests to `v26.0`. Before changing
it, review Meta's Marketing API changelog and version lifecycle, update the
constant, and run the provider and integration contract tests. Repeat live
identity, permission, discovery, and app-secret checks with designated test
assets. Record the tested version and its confirmed deprecation date with the
qualification evidence. No live lifecycle result is recorded here.

## Replace or revoke a token

Replace an expired or revoked token through the existing connection recovery
flow. To invalidate it at Meta, revoke it in **Business Settings > Users >
System users**. Removing the Praxis connection removes the stored credential
through the shared deletion path; it does not revoke the token at Meta.

## Live qualification record

On 24 September 2026, the maintainer accepted the setup assumptions and waived
live checks for implementation. These checks were not performed. No live
credential or designated test-asset evidence is recorded.

For deployment qualification, record the date, Graph version, app mode,
permission access levels, and anonymised asset aliases for these checks:

| Check | Evidence still required |
| --- | --- |
| Partner access | Read and designated reversible write on an owned and a partner ad account; required operation on a partner Page |
| Identity and discovery | System user identity, granted permissions, and populated account tasks for owned and partner assets |
| App secret | Successful correct proof and redacted exact error bodies for missing proof and a second app's token |
| API tier | Initial tier and the dashboard's Full access request prerequisites |
| Connection UI | Owned and partner discovery, selection beside a Google Ads account, and read-only reporting access |
| Recovery and secrecy | Invalid-token and wrong-app guidance, with no token or proof in logs or audit evidence |

Keep tokens, secrets, proofs, identifying asset values, and echoed URLs out of
the record. Consult Meta's [system user overview](https://developers.facebook.com/docs/marketing-api/system-users/overview),
[request security guidance](https://developers.facebook.com/docs/graph-api/securing-requests),
[Marketing API authorisation](https://developers.facebook.com/docs/marketing-api/get-started/authorization),
and [versioning reference](https://developers.facebook.com/docs/marketing-api/overview/versioning)
when qualifying a deployment. Attempts to retrieve the first three references
on 24 September 2026 failed; the documentation lookup is not live API evidence.
