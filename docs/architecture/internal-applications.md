# Internal applications

- **Status:** Pending. The applications capability isn't implemented. Unless a
  section explicitly identifies existing infrastructure, every present-tense
  statement below defines a design requirement rather than available behavior.
  Applications must use the platform's identity, dispatch, policy, and audit
  boundaries.
- **Rule:** Implementation work cites the section it implements. Record any
  deviation in this note in the same pull request.
- This note contains **architecture, not product scope**. Intake flows,
  triage policy, and catalog user experience are product decisions. This note defines where an
  application's code lives, what it may touch, and who may change what is
  this note's.

## 1. Objective

The proposed capability lets people inside an organization use AI coding tools
to build shared internal applications. Applications use Praxis identity,
credentials, storage, permissions, approvals, audit, and lifecycle controls.
Praxis provides the architecture, and builders provide the workflow.

Two constraints shape everything below, both taken as product decisions:

1. **One place.** Applications run inside the organisation's Praxis
   deployment, under Praxis identity, on Praxis surfaces. No separately
   hosted services, no external identity federation, no second admin
   plane.
2. **Built anywhere.** Builders author applications locally with their own
   coding tools (Claude Code, Codex, Cursor) on their own subscriptions.
   Praxis is not the required build environment and carries no build-time
   model spend. In-workspace application authoring is a possible later entry
   point, not a required path.

These constraints separate build time from run time:
**applications are built anywhere, published into Praxis, and run inside
it.**

## 2. Core position: applications are workspace content, not deployments

An application is a proposed workspace resource, like agents, skills, and
files. It isn't a separately deployed service:

- **What it is**: a versioned application contract (§7) + a static
  frontend bundle + configuration that _references_ Praxis resources
  (which registry tools it may call, which data collections it owns,
  which agents/schedules it uses).
- **Where the bytes live**: the bundle is object storage content versioned
  by the existing `File`/`FileRevision` machinery (immutable revisions,
  provenance, retention).
- **Where it runs**: in a sandboxed frame inside the Praxis shell. The
  user never leaves Praxis; the app never gets an origin of its own
  outside Praxis control.
- **Publishing** is a state change on the application row (draft →
  published to an audience), not a deployment. Rollback is pointing the
  current-version pointer at a prior revision. Disable is a flag.
  Retirement is soft delete under the standard retention laws
  (`governance.md` §3).

This choice has the following consequences:

| Lifecycle concern                | Becomes                                                |
| -------------------------------- | ------------------------------------------------------ |
| Deployment, versioning, rollback | `FileRevision` semantics + a current-version pointer   |
| Catalogue                        | a workspace list surface over application rows         |
| Audience control                 | workspace membership/roles at read time (groups later) |
| Ownership, transfer              | columns + ordinary CRUD, audited                       |
| Audit and incident history       | existing `audit_events`, actor = user _via_ app        |
| Disable/revoke                   | row flag checked at frame mint and token verify time   |

This is where the codebase already points: artifacts serve versioned HTML
bundles sandboxed with strict CSP, and dormant scaffolding exists for exactly
this surface — `middleware/utils.py` matches `/apps/{id}/frame` paths,
`middleware/security_headers.py` relaxes `frame-ancestors` for them, and the
CORS allowlist already carries `X-Praxis-App-Frame-Token`. Internal
applications extend artifacts with a bundle, contract, scoped capabilities,
and an audience.

## 3. The three-tier change model

The design separates application work from core platform changes. It defines
three change tiers, each with an owner, artifact, and route:

| Tier                                                                             | Who ships it                          | Artifact          | Route                                                                   | Repo access   |
| -------------------------------------------------------------------------------- | ------------------------------------- | ----------------- | ----------------------------------------------------------------------- | ------------- |
| **Application** — workflow, UI, config, business rules                           | Internal builder + their coding agent | Contract + bundle | Push/upload → validation gates → draft → publish                        | None          |
| **Building block** — new tool, provider operation, collection type, UI component | Platform/technical owner              | In-repo package   | Normal review, following the packaging law (`integration-packaging.md`) | Yes, isolated |
| **Platform** — dispatch, identity, contracts, policy, serving                    | Core maintainers                      | Core code         | Normal review                                                           | Yes           |

- Builders **cannot** reach the repository. An application that needs a
  capability no existing building block provides produces a **capability
  request** (the brief's exception path), which a technical owner may
  implement as a tier-2 package — contribution stays isolated by the same
  import laws and enablement layers that govern integration providers.
- Tier 2 uses an established shape: self-contained packages, startup
  enablement, AST-enforced import laws, one-line registration, default
  server-declared UI. Building blocks beyond integrations (e.g. an app
  data collection type) follow the same law.
- Enforcement never distributes. Registry, dispatch, credential handling,
  approvals, audit, and token minting stay singular
  (`integration-packaging.md` §2 principle 1 applies unchanged).

## 4. Identity and capability scoping

There is no external identity system. The app runs inside an
authenticated Praxis session, and identity work reduces to one scoped
token mechanism with two mint paths.

### 4.1 Frame tokens (runtime)

1. A user opens a published app from the catalog. They are already
   authenticated, workspace-resolved, and role-checked by the existing
   dependency stack.
2. The server mints a **short-lived frame token** from that session:
   - principal: the user in the workspace (apps are never their own
     principal);
   - audience: the application id + version;
   - scopes: exactly the building blocks the application contract
     declares — never more, regardless of the user's role.
3. The sandboxed bundle calls the Praxis API bearing that token. Routes
   on the app capability surface (§5) verify audience and scope on every
   call.

The app is therefore a **narrower principal than its user**. A faulty or
malicious generated bundle can only do what its contract declares, and
only on behalf of a user entitled to do it anyway. Every audit row
records (user, via application X, version N).

Non-goals, explicitly: no OIDC/OAuth2 provider capability, no personal
access tokens as a general API surface, no service accounts, no machine
principals. If a future need arises for genuinely external callers, that
is a separate architecture decision, not an extension of this one.

### 4.2 Development tokens (build time)

The second mint path for the same verifier. From the application's page,
its owner creates a **development token**: same principal model, same
contract-derived scopes, longer-lived (bounded), revocable, audited, and
displayed once. The builder drops it in `.env.local`.

- **[default — confirm at review]** Dev tokens are read-scoped by
  default; write scopes are an explicit per-token toggle. App data
  collections resolve to a scratch/dev namespace under a dev token so
  builders do not iterate against shared rows.
- Dev tokens are a human's scoped credential for a build loop — they do
  don't create machine identity, and they never appear in a published
  bundle (the validation gates reject any embedded credential, and the
  dev harness design in §6 keeps them out of browser code entirely).

### 4.3 CORS and CSRF posture (unchanged)

Production CORS, cookie, and CSRF posture is not loosened
(AGENTS.md security constraints). Frame tokens are same-origin. Local
development never talks cross-origin to the API from a browser: the app
template's dev server proxies `/api/*` to the configured Praxis instance
and attaches the dev token server-side (§6.2). Bearer-token requests are
already outside the cookie-CSRF path by design.

## 5. Runtime enforcement boundary

Policy checks are insufficient if the runtime permits an
application to bypass Praxis. The boundary is structural:

### 5.1 The sandbox

The bundle is served on the artifact-style sandboxed surface (the artifacts
three-layer defense, extended): opaque/isolated origin,
`sandbox` attributes, and a strict CSP whose `connect-src` allows **only
the Praxis API origin** (the deliberate difference from artifacts'
`connect-src 'none'`). Consequences, enforced by the browser rather than
by scanning generated code:

- no undeclared external network access;
- no direct database, storage, or provider access — the only reachable
  surface is the app capability API;
- no credential exposure beyond the short-lived, scope-limited frame
  token;
- no cross-app or cross-workspace reach (audience-checked at mint,
  scope-checked per call, and workspace-scoped rows in storage).

### 5.2 The app capability surface

A deliberately narrow API, every route requiring a frame/dev token and
enforcing contract scopes:

| Capability                  | Backed by                                                                                                                                                        | State                                                                |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Execute registry tool       | **Headless dispatch** — a non-agent entrypoint over the existing choke point (`services/agents/runtime/dispatch.py`), with an envelope minted for app principals | Pending; the dispatch module reserves this seam ("wrap this module") |
| App data collections        | Proposed app data service on the reserved `app` schema (`AppModel` base and empty `app` Alembic branch exist; no tables exist)                                   | Pending, bounded                                                     |
| Files                       | Existing files service, app-scoped key namespace                                                                                                                 | Pending extension                                                    |
| Invoke an agent / read runs | Existing agent runtime and runs API, scope-gated                                                                                                                 | Pending extension                                                    |
| Approvals                   | A generic approval primitive, separate from a paused conversation and surfaced in the existing approvals UI                                                      | Pending                                                              |

Server-side application logic beyond this surface is not hosted.
Behavior that needs server-side trust uses Praxis primitives, such as an
agent, schedule, job handler, or registry tool. If it
cannot be, that is a tier-2 capability request by design. The underlying
Python that calls provider APIs lives in exactly one place — registry
tools inside provider packages holding centrally-managed credentials —
and applications reach it only through dispatch.

### 5.3 Effects, approvals, audit

- Tool effect/scope classification, approval defaults, and the spend rule
  apply to app-originated calls exactly as to agent calls
  (`governance.md` §2). The app-principal envelope defaults external
  writes to `require_approval`; **[default — confirm at review]** app
  contracts may not weaken a tool's `supports_auto=False`.
- Every dispatch through the app surface writes the same tool-invocation
  audit rows (args digest, outcome, latency), attributed (user, via app,
  version).
- App-fetched provider content shown back to users is data display, not
  model context; if an app feeds content into an agent run, the existing
  threat-model channels apply unchanged (`threat-model.md` §2).

### 5.4 Known failure modes and countermeasures

| Brief failure mode                             | Countermeasure                                                                      |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| Data embedded in source/HTML                   | App data service + validation gate (inline-data budget)                             |
| Persistence via downloads/self-modifying files | Immutable revisions; bundle is read-only at runtime; collections are the write path |
| Credentials in code or browser config          | Secrets never reach builders; dev proxy keeps tokens server-side; secret-scan gate  |
| Direct DB/external API access                  | CSP `connect-src` allowlist; no DB surface exists to reach                          |
| No shared authn/authz                          | Frame runs inside Praxis session; contract-scoped tokens                            |
| Undeclared side effects                        | Effect-classified dispatch + envelope + approvals                                   |
| No audit/approval boundary                     | Single choke point; app calls cannot route around it                                |
| No deployment/versioning/ownership             | Rows + revisions + owner columns (§2)                                               |
| Unbounded dependencies/infrastructure          | Bundle is static assets; there is no infrastructure to request                      |

## 6. The build loop (local-first)

### 6.1 Application kit

`praxis create-app` (or a template repository) scaffolds a normal web
project:

- Vite and the approved UI component baseline;
- a typed client for the app capability surface (generated from the
  authenticated OpenAPI schema route);
- a manifest/contract stub;
- **coding-agent instructions** in `AGENTS.md` and `CLAUDE.md`, plus a
  machine-readable building-block catalog snapshot. The snapshot contains
  tool names, input and output schemas, effects, approval defaults, and
  example calls. Claude Code, Codex, and Cursor discover capabilities by
  reading repository files. The development token refreshes the snapshot
  from the live catalog route.

All build-time model spend is on the builder's own tooling subscription.
Praxis model spend occurs only when a published app invokes agents or
models at runtime, metered by the existing per-run usage accounting.

### 6.2 Dev harness

The template's development server serves the bundle locally in a shell-emulating
frame and proxies `/api/*` to the configured Praxis instance, attaching
the dev token server-side. The browser only ever talks to localhost;
production CORS is unchanged. The token stays out of client code.

### 6.3 Publish

The `praxis apps push` command-line interface (CLI) or UI upload sends the
bundle and manifest. After receipt, the server runs these validation gates:

- secret/credential scan; inline-dataset and generated-binary budgets;
- manifest ↔ requested-scope consistency; every requested building block
  exists and is enabled;
- CSP compatibility (no external asset references, no forbidden
  directives);
- ownership and audience declared; maintainability budgets
  **[default — confirm at review]**.

Failures return a machine-readable report that names the violated contract
and supported replacement. A coding agent can apply this feedback directly.
A successful validation creates a draft version that an owner can publish to
the intended audience. The CLI can also support a future CI workflow.

## 7. Application contract (minimum viable)

Versioned, machine-readable, stored with the application row; drives
provisioning, token scoping, validation, catalog, and audit — never
documentation-only. Minimum fields:

- application id, version, title, purpose;
- owner (accountable user) and fallback owner;
- audience (workspace roles v1; groups when they exist);
- requested building blocks: tool names, collection declarations, file
  namespace, agent/schedule references;
- effect expectations: reads, writes, external side effects; approval
  posture per declared write;
- storage/retention expectations for its collections;
- support class **[default — confirm at review]** (best-effort v1).

Changes that widen audience, add write scopes, or add sensitive resources
re-enter validation rather than inheriting a prior approval — enforced by
scope-diffing contract versions at publish time.

## 8. Existing foundation

| Need                            | Existing asset                                                                                               | Gap                                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| Capability contract             | `RuntimeToolDefinition` — effect, effect_scope, policies, output model, presentation, import-time validation | No serialized **input** JSON Schema in the catalog and no `version` field on tools; adding either later requires a migration |
| One audited execution path      | `dispatch.py` choke point + envelopes + audit                                                                | Agent-run-coupled; needs the headless entrypoint + app-principal envelope                                                    |
| Approvals                       | Suspend/resume + approvals UI                                                                                | Conversation-coupled; needs a generic primitive                                                                              |
| Per-workspace capability gating | `is_tool_allowed` seam + per-agent tool policies                                                             | No per-workspace grant model                                                                                                 |
| Credentials/secrets             | Integration credential engine + secrets providers                                                            | None for this note's purposes                                                                                                |
| Versioned content + serving     | Files/`FileRevision`; the artifacts serving pipeline; `/apps/{id}/frame` middleware scaffolding              | App serving route, mint/verify, and bundle conventions unbuilt                                                               |
| App data                        | `app` schema, Alembic branch, and `AppModel` base                                                            | The collection service requires its first tables and implementation                                                          |
| Background work                 | Generic jobs harness                                                                                         | App-attributed enqueue conventions only                                                                                      |
| Governance/threat model         | `governance.md`, `threat-model.md`                                                                           | New rows/sections, same shape                                                                                                |
| Working integrations to compose | OAuth, API-key, and service-account connections with discovery and context selection                         | None for this note's purposes                                                                                                |

## 9. Non-goals

- Hosting arbitrary backend code, runtimes, or infrastructure.
- External identity: OIDC provider, PATs-as-API, service accounts,
  machine principals.
- Externally-deployed applications consuming Praxis remotely.
- Making arbitrary generated software safe; replacing professional
  engineering for systems of record or customer-facing products.
- Automatic generation of new integrations from prompts (new providers
  are tier-2 human-owned packages).
- Public/external-user exposure of applications.

## 10. Open decisions

Resolve these decisions before implementation starts. The list includes
proposed defaults:

1. First supported application shape and a first reference application
   (internal, read-mostly, recognizable to a non-technical operator) —
   maintainer decision.
2. Frame/dev token mechanics: lifetime, storage, revocation, and whether
   dev tokens default read-only (§4.2 default).
3. App data service v1 scope — default: schemaless JSONB + quotas.
4. Whether app-owned schedules ship in v1 (via a referenced agent) —
   default: not in v1; the contract's agent/schedule references (§7)
   reserve the seam.
5. Validation gate set for v1 and which checks must be runtime
   enforcement rather than publish-time validation.
6. Where the UI component baseline for templates comes from (shared
   package vs copied scaffold) — default: copied scaffold.

## 11. Adjacent notes

`governance.md`, `threat-model.md`, `integration-packaging.md`, and
`agent-runtime.md`.
