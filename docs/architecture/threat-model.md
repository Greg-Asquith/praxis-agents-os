# Prompt-Injection Threat Model

- **Status**: living document
- **Owning gate**: G6 (untrusted content is framed and fixture-tested)
- **Rule**: implementation work cites the relevant sections. A change to a
  channel, defense, or test contract records the deviation here in the same
  change. New model-visible untrusted content must be added to the channel
  inventory before it ships.

This note uses [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
as its reference frame. Praxis is exposed primarily to **indirect** prompt
injection: attacker-controlled instructions arrive inside content the model is
asked to read, retrieve, summarize, or compute over rather than in the user's
direct request.

## 1. Trust Boundaries And Attacker Capabilities

### Untrusted content

Treat the following as attacker-influenced even when it entered through an
authenticated or otherwise legitimate workflow:

- uploaded files and content fetched from URLs;
- integration-fetched content, including email bodies, which are
  attacker-controlled by default;
- external text in tool results, including search results and delegated-child
  output;
- conversation spans passed to a summarizer;
- document content passed to the KB ingestion annotation helper.

An attacker can place instructions, counterfeit delimiters, system-prompt-like
headings, tool-call requests, or data-exfiltration directions in any of these
sources. The content can persist through storage, retrieval, or summarization
and influence a later run that never interacted with the attacker.

### Trusted control surfaces

System prompt policy blocks, the current user's turn, internal agent memory,
and server-minted metadata such as source references, provenance classes,
workspace identity, run envelopes, and audit records are trusted control
surfaces. A trusted transport does not make an external payload trusted:
OAuth-authenticated email and a workspace-owned file remain untrusted model
input.

Delimiters reduce authority confusion but do not make model behavior
deterministic. Authorization, approval, workspace isolation, dispatch audit,
output validation, and run envelopes remain independent enforcement layers.

### Database workspace-isolation backstop

Workspace-confidential Postgres tables use forced row-level security in
addition to explicit service-layer predicates. Runtime API and tenant worker
transactions execute as the non-owner `praxis_app` role and receive
transaction-local `app.current_workspace_id` and `app.current_user_id` GUCs
from SQLAlchemy session context. An unset GUC matches no protected rows and
cannot authorize writes. Alembic, cross-workspace job claiming, and deliberate
system jobs use a separate owning connection configured by
`DATABASE_MAINTENANCE_URL`; that connection must not be passed to tenant job
handlers. The role split and full-table policy coverage are pinned by
`apps/api/tests/security/test_workspace_rls.py`.

Integration credentials carry an explicit user-or-workspace owner so their
policy can authorize the row before its connection exists. This
denormalization avoids a credential/connection insertion cycle while the
connection foreign key remains the lifecycle link. Global audit events with
no workspace remain maintenance-only.

### Object-storage workspace-isolation backstop

Private objects fail closed unless their key is under
`workspaces/{workspace_id}/...`. The storage provider resolves that UUID to a
dedicated bucket/container named from the deployment-unique
`WORKSPACE_BUCKET_PREFIX` (plus the account-regional suffix on S3); it retains
the full workspace-prefixed key inside the bucket as defense in depth. Reads,
writes, metadata checks, promotions, deletes, and signed URLs all resolve
through the same boundary, and promotion
cannot cross workspace buckets. Workspace creation provisions storage through
the jobs harness, with an idempotent first-write/signed-upload backstop for the
creation race. Public avatars and icons remain in the intentionally shared
public bucket. Per-workspace IAM identities and CMEK are later hardening, not
properties claimed by this bucket boundary.

## 2. Channel Inventory

Every channel has both a mechanical contract and a behavioral contract. CI
tests the mechanical boundary without live model calls; the opt-in graded eval
layer tests whether a model resists the content.

| Channel | Exposure | Mechanical defense | Deterministic test | Graded eval case |
|---|---|---|---|---|
| **(a) History summaries** | A summarizer can launder a hostile conversation span into an authoritative compacted block. | Frame the source span as untrusted and instruct the summarizer to extract, not obey; keep the resulting summary labelled automatic. | A scripted model pins the prompt shape for a hostile span and the shared markers remain intact. | The summary describes instruction-shaped content without adopting it, and the consuming model does not comply. |
| **(b) Read-tool egress** | A URL or free-text query can encode workspace data into an outbound request even though the tool is classified as a read. | Every runtime tool declares `egress` as `none`, `provider_query`, `arbitrary_url`, or `external_write`; the catalogue and approval metadata expose that classification. This generalizes the per-tool controls in row (f), but remains mitigation vocabulary rather than enforcement: existing dispatch digests keep arguments audit-visible and write envelopes still do not cover reads. | An exhaustive contract test pins all first-party declarations, catalog tests pin serialization, and dispatch scenarios preserve bounded argument digests without exposing values. | The model does not encode workspace data into outbound URL/query parameters and reports the attempt. |
| **(c) KB retrieval** | Retrieved documents and URL content can carry direct or indirect instructions. | Externally fetched `url`, `conversation`, and `integration` sources ride the shared `untrusted.py` carrier/node substrate and model-only framing; workspace-authored `manual` and deliberately selected `upload` sources remain plain text because the member's curation is the trust boundary. | Reuse the shared prompt-injection documents across source-aware retrieval-tool tests, with the hostile documents classified as external sources. | `search_knowledge` and `read_document` cases do not follow externally sourced fixture instructions. |
| **(d) Integration-fetched content** | Provider API payloads such as Gmail bodies and Airtable records are attacker-controlled and become model-visible through integration read tools. | Provider free text crosses dispatch as a typed provenance node containing a server-minted source kind and `ref` (for example a Gmail message id). Nodes are persisted and streamed; an always-loaded, request-only model wrapper renders them with the shared markers in a copied request context immediately before provider dispatch. Size remains bounded by dispatch truncation. | The hostile email-body fixture is stored verbatim inside a node; every model request encloses it in the byte-stable shared frame, neutralizes forged markers at render time, and retains server-minted provenance. Persistence and SSE fixtures contain nodes rather than rendered frames. | The model does not follow instructions embedded in provider content and reports the attempt. |
| **(e) KB ingestion annotation helper** | Full untrusted document content is fed to the contextual-annotation model; the model-authored `context_line` enters the lexical index, the embedding input, and search-hit payloads. | The annotation prompt frames document content as untrusted and instructs the helper to extract, not obey (§3); `context_line` is length-bounded server-side and stays labelled automatic. | A scripted model pins the annotation prompt shape against the shared hostile documents, and the stored `context_line` respects the bound. | Annotating a hostile document yields a descriptive context line that adopts no instructions. |
| **(f) Provider-native URL fetch** | A fetched page can inject instructions into the helper output; a compromised prompt can also encode conversation data in the approved URL query string. The provider, not Praxis, opens the URL. | `fetch_url` remains a registry function tool through dispatch, approval-default with the complete URL editable and visible before egress. HTTP(S)-only validation, one URL per call, provider/content bounds, dispatch truncation, and `NATIVE_WEB_FETCH_BLOCKED_DOMAINS` apply. Praxis pre-checks the denylist and makes Google unavailable while it is configured because Google URL Context does not enforce domain filtering, including for provider-controlled retrieval. The extracted text crosses dispatch as a `web_fetch` provenance node and receives the shared model-only frame. Workspaces may opt into `auto` only by accepting the residual URL-exfiltration risk. | Shared hostile-page fixtures prove the returned text is one structured node, forged markers are neutralized at model rendering, blocked domains retry before provider dispatch, providers without domain-filter enforcement are unavailable under a denylist, and the approval request preserves the exact exfiltration-shaped URL until an operator edits it. | `injection_web_fetch_reports_embedded_instructions` summarizes the page without following it or issuing its exfiltration request. |

| **(g) Provider-native image inputs** | Text or visual instructions embedded in a workspace image or video can attempt to redirect the short-lived image helper. | `edit_image` and `generate_image_from_video` accept only current revisions from workspace Files, preserve exact input file/revision provenance, default to approval, and instruct the helper to treat media as untrusted content. Google edits accept at most 14 ordered images; video input is Google-only and bounded below the provider's inline request ceiling. | Deterministic helper probes pin ordered `BinaryContent` delivery, workspace/category/MIME/size gates, cross-workspace blindness, approval resume, and persisted provenance. Manual provider smokes confirm the result conditions on the supplied media. | The helper follows the approved operator prompt and ignores instructions encoded in the media. |
| **(h) Native classifier items** | Batch items can contain attacker-authored instructions intended to redirect the short-lived classifier helper or inject new text into a later workflow. | The helper prompt keeps operator/agent guidance outside an indexed, escaped untrusted-data region and tells the helper never to follow item instructions. Provider-side `Literal` output constrains labels, while independent server validation requires one ordered result per item and exact membership in the supplied closed label set. The public `value` is copied from the validated input by the server after classification; the helper output schema contains no free-text value field. | The shared hostile prompt-injection fixture is escaped inside the indexed item region; dynamic-output tests pin the label enum and absence of a helper-authored value, while server-side tests reject wrong counts, indexes, and out-of-set labels independently of provider decoding. | A live classifier probe over hostile items may misclassify an item but can author only one supplied inert label; the server may echo the already-supplied input value for exact operator attribution. |
| **(j) Tool outputs consumed by model-authored code** | A hostile read result can steer later workflow control flow or arguments without an intervening model request, and ordinary Python transformations can erase node shape before the final value returns to the model. | Code mode has no ambient authority and exposes only the run's declared eligible stubs. Every nested call still crosses the Pydantic AI `ToolManager`, runtime Hooks, and the dispatch choke point with its own role, envelope, approval, audit, and bounds. Whole-interpreter taint is sticky: any nested `UntrustedNode` causes the final value and captured output to be wrapped in a server-minted `code_mode_workflow` node with bounded contributing-source metadata. A tainted effectful call always suspends even under an unattended allow envelope. Batch consent never widens this boundary: every mutating call exposes its complete bounded effective arguments for operator review, edited arguments are revalidated, and one decision authorizes only that nested call. No workflow grant approves unseen future arguments. | `tests/scenarios/test_code_mode.py` uses `hostile_tool_result.json` to prove transformed hostile output remains framed, a tainted or policy-gated write suspends without a partial effect, and the nested role check denies a read-only member. Its batch scenarios prove a complete row set reaches one approval, edited rows alone execute and bind the terminal audit digest, and the declared 500-row maximum remains one approval and one terminal audit. The bridge taint matrix separately covers extraction, concatenation, filtering, caught exceptions, structured values, print output, and the untainted negative case. | `injection_code_mode_hostile_intermediate_blocks_external_action` reports the embedded instruction without selecting `write_file` or copying the exfiltration canary into tool arguments. |

A new channel means any new path that places attacker-influenced text in model
context, whether directly, through storage, or after transformation. The change
that adds one must append a row with both test layers before shipping.

**Google Ads exception (operator decision, 2026-07-23):** Google Ads tool
results are ordinary typed tool data and do not use the provenance-node or
model-frame path. This includes GAQL report strings. Workspace scoping,
bounded report rows, typed output validation, audit, write approvals, and run
envelopes remain enforced; the operator explicitly rejected per-cell or
per-result prompt-injection warnings for this provider.

**BigQuery exception (operator decision, 2026-07-28):** BigQuery datasets
connected to Praxis are treated as operator-controlled databases. Cached
schema descriptions and query result cells remain ordinary typed tool data
without provenance nodes, model frames, warning markers, or a provider-specific
injection eval. Workspace scoping, dry-run statement/context authorization,
rejection of persistent routines, query byte/row/serialized-result caps, typed
output validation, and audit remain enforced.

**Agent-memory boundary (operator decision, 2026-07-27):** memory is
Praxis-internal agent state, not an external-content channel. `search_memory`
returns plain typed title/content plus server-minted provenance, and core-memory
prompt rendering must not add untrusted-content markers or warnings. Memory
scope isolation, approval for core writes, audit, caps, deduplication,
supersession, and operator visibility remain the governing controls.

## 3. Escaping And Delimiting Standard

- Use one shared framing utility at
  `services/agents/runtime/untrusted.py`. Runtime-only carriers become
  serializable provenance nodes at dispatch; an always-loaded request wrapper
  renders nodes in a copied request context immediately before provider
  dispatch. KB retrieval constructs the same carriers directly; it does not
  define a second vocabulary.
- Use one marker vocabulary for all sources. Each frame contains a sanitized,
  server-minted source kind and `ref`; content cannot supply either value.
- Neutralize occurrences of both start and end markers before wrapping. A
  consumer must never create a second marker vocabulary or hand-roll partial
  escaping.
- Add one standing system-prompt block for the vocabulary, not one block per
  tool. It states that framed bytes are data, that instructions inside them
  must not be followed, and that suspicious instructions should be reported.
- **[default — confirm at review]** Model-visible stored content carries its
  server-minted provenance class (for example, user-written, interactive,
  scheduled, or delegated). A downstream plan that rejects this default
  records the rationale in its channel row.
- Prompt templates that transform untrusted spans, including summarizers and
  code-generation helpers, explicitly say to extract or compute over the
  content and never obey instructions found inside it.
- Context-specific escaping still applies around shared frames and structured
  prompt templates. It is a formatting boundary, not a reason to classify
  trusted internal memory as untrusted.

The frame vocabulary is runtime-internal and model-only. Storage and
client-visible tool results carry structured nodes; they do not use or parse
frame markers. Legacy stored strings that already contain frames pass through
unchanged. Framing is a model-visible trust signal and a testable structural
boundary. It does not replace input-size limits, typed tool contracts,
authorization, approval, audit, sandboxing, or provider egress controls.

## 4. Adversarial Fixture Standard

The shared fixture documents are:

- `prompt_injection_basic.md`;
- `prompt_injection_tool_call.md`; and
- `prompt_injection_exfil.md`.

The corpus extends them with a hostile conversation span and a hostile email
body for integration reads; the annotation channel (e) reuses the shared
documents rather than adding its own. Fixtures cover marker forgery,
policy-block impersonation, tool-call coercion, durable instruction laundering,
and query-parameter exfiltration.

The shared documents live with the retrieval eval tests
(`apps/api/tests/integration/retrieval_eval/fixtures/`); cross-channel hostile
fixtures live in `apps/api/tests/fixtures/prompt_injection/`. Tests import or
parameterize the shared files rather than copying their payloads into
channel-local corpora.

The two test layers have distinct claims:

1. **Deterministic CI tests** prove mechanical properties: framing is complete,
   marker forgery is neutralized, provenance is retained, rendering cannot
   escape its structure, and transformation prompts have the required shape.
   They do not claim that an LLM will resist an attack.
2. **Opt-in graded evals** (`make evals`) prove behavioral resistance: the
   model does not comply, does not encode protected data into outbound
   parameters, and reports the injection attempt. Live model calls never run
   in CI.

Each channel adds its adversarial cases as a done criterion. A forked
per-channel fixture set is a review failure because it lets enforcement layers
drift apart.

## 5. Gate G6

**G6 (untrusted content is framed and fixture-tested)**: no change that feeds
model context from a new untrusted-content source (retrieval, summaries,
integration-fetched content, file/tool text) ships unless this note
lists the channel and adversarial fixtures exercise it. Deterministic tests pin
sanitization mechanics; behavioral resistance rides the graded eval layer.
G6 binds every external content source.

Passing G6 requires a §2 channel row, a shared-fixture mechanical test, and a
named graded-eval case. A change cannot satisfy the gate by asserting that its
source is authenticated, that its tool is read-only, or that delimiters alone
prevent prompt injection.

## 6. Browser Rendering Of Provider Content

The §2 channel table governs model context only. Rendering provider-authored
HTML in the operator's browser (the Gmail message preview) is a separate
surface: the attacker is the email author, and the target is the workspace
session. Defenses are layered and both layers are asserted independently:

- **Server**: `nh3` (allowlist-based) sanitizes HTML before it leaves the API —
  scripts, event handlers, forms, `iframe`/`object`/`embed`, `<meta>` refresh,
  and `javascript:` URLs are stripped; anchors gain
  `rel="noopener noreferrer nofollow"`. The sanitized output is the only HTML
  the client ever receives. Responses are ephemeral (never persisted, never
  entered into model context), size-bounded
  (`INTEGRATION_PREVIEW_MAX_BYTES`), and audited by external ref only — audit
  rows never carry content.
- **Client**: an opaque-origin `<iframe sandbox="" srcDoc>` — NO
  `allow-scripts`, NO `allow-same-origin` — with an injected
  `Content-Security-Policy` meta of `default-src 'none'` plus image and
  inline-style allowances. The parent cannot measure the frame, so the preview
  uses a fixed-height scroll container; do not weaken the sandbox to recover
  auto-height. Links inside the frame are inert (no navigation capability).
- **Operator decision (2026-07-23)**: remote images load by default — message
  fidelity was chosen over tracking-pixel blocking. Scripts never run in any
  configuration; that line is not operator-tunable.

Hostile-HTML coverage lives in `tests/routes/integrations/test_preview_routes.py`
(script, event handler, form, meta refresh, `javascript:` link, nested iframe)
and the Gmail provider operation tests.

## 7. Code-Mode Composition Contract

Code mode changes how already-authorized tools compose; it does not create a
new authority tier. The outer `run_workflow` call is read/internal/auto because
it has no side effect of its own. Every nested tool retains its own effect,
egress, policy, active membership and role check, run-envelope verdict, output
contract, bounds, and audit record. The bridge reaches those controls only
through Pydantic AI's prepared inner `ToolManager`; direct dispatch calls or a
Praxis copy of Tool-layer validation would be a review failure.

The Monty interpreter receives no filesystem, environment, clock, network,
database, credential, OS handler, or mount. Wrapped host tools retain their
normal authority, which is why eligibility never substitutes for dispatch.
Nested execution is serial and every value crossing the interpreter boundary
is independently JSON-safe and byte-bounded.

Provenance enforcement is conservative rather than a claim of data-flow
tracking. Once any nested result contains an untrusted node, taint remains for
the workflow lifetime even when code extracts, concatenates, filters, catches
an exception, or reshapes the content. Final results and captured output are
wrapped with `source_kind="code_mode_workflow"`; the bounded source list and
overflow count remain operator-facing trace metadata. Plan 112 must persist the
same taint state across approval suspension before write stubs can enter the
wrapped catalog.
