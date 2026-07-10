# Prompt-Injection Threat Model

- **Status**: living document
- **Owning gate**: G6 (untrusted content is framed and fixture-tested)
- **Written**: 2026-07-10 (plan 075)
- **Amended**: 2026-07-10 (plan 080 — channels (g) integration-fetched
  content and (h) KB annotation helper; hostile email-body fixture)
- **Rule**: downstream plans implement slices of this note and cite the
  relevant sections. A plan that changes a channel, defense, or test contract
  records the deviation here in the same change. New model-visible untrusted
  content must be added to the channel inventory before it ships.

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
  attacker-controlled by default once Gmail lands;
- external text in tool results, including search results and delegated-child
  output;
- stored memory content authored by an agent during a run;
- conversation spans passed to a summarizer;
- file content passed to a helper model for code generation; and
- document content passed to the KB ingestion annotation helper.

An attacker can place instructions, counterfeit delimiters, system-prompt-like
headings, tool-call requests, or data-exfiltration directions in any of these
sources. The content can persist through storage, retrieval, summarization, or
memory and influence a later run that never interacted with the attacker.

### Trusted control surfaces

System prompt policy blocks, the current user's turn, and server-minted
metadata such as source references, provenance classes, workspace identity,
run envelopes, and audit records are trusted control surfaces. A trusted
transport does not make its payload trusted: OAuth-authenticated email and a
workspace-owned file remain untrusted model input.

Delimiters reduce authority confusion but do not make model behavior
deterministic. Authorization, approval, workspace isolation, dispatch audit,
output validation, and run envelopes remain independent enforcement layers.

## 2. Channel Inventory

Every channel has both a mechanical contract and a behavioral contract. CI
tests the mechanical boundary without live model calls; the opt-in graded eval
layer tests whether a model resists the content.

| Channel | Exposure | Mechanical defense | Deterministic test | Graded eval case | Owner |
|---|---|---|---|---|---|
| **(a) Memory writes and search** | Instructions saved during one run persist and return through `search_memory` later. | Frame stored content on read with the shared markers; neutralize forged markers; surface server-minted source and creator provenance. | Hostile title/content survives save→search inside one frame, forged markers cannot close it, and provenance is present. | The model neither follows nor propagates a hostile memory and reports the attempt. | 048 |
| **(b) Core-memory prompt injection** | Stored memory is interpolated into the highest-authority prompt surface. | Escape title/content so it cannot create headers, lines, or policy blocks; surface a provenance class. | Hostile memory fixtures cannot escape their line, forge `## Memory`, or impersonate `memory_policy`; output stays byte-stable. | The model treats hostile core memory as stored data, not a new instruction. | 049 |
| **(c) History summaries** | A summarizer can launder a hostile conversation span into an authoritative compacted block. | Frame the source span as untrusted and instruct the summarizer to extract, not obey; keep the resulting summary labelled automatic. | A scripted model pins the prompt shape for a hostile span and the shared markers remain intact. | The summary describes instruction-shaped content without adopting it, and the consuming model does not comply. | 056 |
| **(d) File content to generated code** | A hostile CSV cell or file passage can steer the helper model that writes code. | Keep task text separate; frame all inlined file content as untrusted before the helper-model call. | The hostile CSV fixture is entirely enclosed by the shared frame and cannot forge its end marker. | Generated code follows the user's task rather than file-borne instructions. Sandbox egress is tested separately by 072. | 059 |
| **(e) Read-tool egress** | A URL or free-text query can encode workspace data into an outbound request even though the tool is classified as a read. | **[default — confirm at review]** Keep query arguments audit-visible through existing dispatch digests; add no new enforcement machinery in v1. Write envelopes do not cover reads. | Assert audit metadata records bounded argument digests without exposing secret values. | The model does not encode workspace data into outbound URL/query parameters and reports the attempt. | 055, with 041/054 context |
| **(f) KB retrieval** | Retrieved documents and URL content can carry direct or indirect instructions. | Wrap every retrieved byte with the shared markers after forgery sanitization; one standing prompt block declares framed content data, never instructions. | Reuse the shared prompt-injection documents across retrieval and tool-framing tests. | `search_knowledge` and `read_document` cases do not follow fixture instructions. | 046 (reference defense), 055 behavioral layer |
| **(g) Integration-fetched content** | Provider API payloads (Gmail bodies, Airtable records, Ads report text) are attacker-controlled and become model-visible through integration read tools. | Provider free text enters model context only through dispatch tool results, wrapped with the shared markers and a server-minted source kind and `ref` (for example a Gmail message id); size is bounded by 076's dispatch truncation. | The hostile email-body fixture is entirely enclosed by the shared frame, forged markers are neutralized, and the source ref is server-minted. | The model does not follow instructions embedded in provider content and reports the attempt. | 041, 055 behavioral layer |
| **(h) KB ingestion annotation helper** | Full untrusted document content is fed to the contextual-annotation model; the model-authored `context_line` enters the lexical index, the embedding input, and search-hit payloads. | The annotation prompt frames document content as untrusted and instructs the helper to extract, not obey (§3); `context_line` is length-bounded server-side and stays labelled automatic. | A scripted model pins the annotation prompt shape against the shared hostile documents, and the stored `context_line` respects the bound. | Annotating a hostile document yields a descriptive context line that adopts no instructions. | 044, 055 behavioral layer |

A new channel means any new path that places attacker-influenced text in model
context, whether directly, through storage, or after transformation. Its plan
must append a row with an owner and both test layers before shipping.

## 3. Escaping And Delimiting Standard

- Use one shared framing utility at **[default — confirm at review]
  `services/agents/runtime/untrusted.py`**. The 046 KB helper moves there
  when its second consumer arrives.
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
- Context-specific escaping still applies around the shared frame. For
  example, core-memory title/content must not be able to create Markdown
  headings or additional list entries.

Framing is a model-visible trust signal and a testable structural boundary. It
does not replace input-size limits, typed tool contracts, authorization,
approval, audit, sandboxing, or provider egress controls.

## 4. Adversarial Fixture Standard

The fixture corpus starts with 045's shared documents:

- `prompt_injection_basic.md`;
- `prompt_injection_tool_call.md`; and
- `prompt_injection_exfil.md`.

It extends them with a hostile memory title/content pair, a hostile
conversation span, a hostile CSV for code generation, and a hostile email
body for integration reads; the annotation channel (h) reuses the shared
documents rather than adding its own. Fixtures cover marker forgery,
policy-block impersonation, tool-call coercion, durable instruction
laundering, and query-parameter exfiltration.

Use **[default — confirm at review]** a hoisted shared fixture directory when
the second non-KB consumer arrives; until then, extend
`tests/integration/retrieval_eval/fixtures/`. Tests import or parameterize the
shared files rather than copying their payloads into channel-local corpora.

The two test layers have distinct claims:

1. **Deterministic CI tests** prove mechanical properties: framing is complete,
   marker forgery is neutralized, provenance is retained, rendering cannot
   escape its structure, and transformation prompts have the required shape.
   They do not claim that an LLM will resist an attack.
2. **Opt-in graded evals** under 055 prove behavioral resistance: the model
   does not comply, does not encode protected data into outbound parameters,
   and reports the injection attempt. Live model calls never run in CI.

Each channel owner adds its adversarial cases as a done criterion. A forked
per-plan fixture set is a review failure because it lets enforcement layers
drift apart.

## 5. Gate G6

**G6 (untrusted content is framed and fixture-tested)**: no plan that feeds
model context from a new untrusted-content source (retrieval, memory,
summaries, integration-fetched content, file/tool text) ships unless this note
lists the channel and adversarial fixtures exercise it. Deterministic tests pin
sanitization mechanics; behavioral resistance rides 055's graded eval layer.
G6 binds 041/044/046/048/049/056/059 and every later content source.

Passing G6 requires a §2 channel row, an explicit owner, a shared-fixture
mechanical test, and a named graded-eval case. A plan cannot satisfy the gate by
asserting that its source is authenticated, that its tool is read-only, or
that delimiters alone prevent prompt injection.

## 6. Consumed By

| Plan | Sections implemented |
|---|---|
| 041 (first integration providers) | §1 external-content boundary; §2(e) integration read/query exposure; §2(g) provider-content framing; §5 gate before Gmail bodies become model-visible |
| 044 (KB models/ingestion) | §2(h) annotation channel; §3 extraction-not-obedience prompt; §4 shared documents |
| 046 (KB tools) | §2(f) reference defense; §3 shared framing vocabulary; §4 KB fixtures |
| 048 (memory model/tools) | §2(a) persistence channel; §3 provenance and read framing; §4 hostile memory fixtures |
| 049 (memory injection/UI) | §2(b) prompt-authority boundary; §3 structural escaping and provenance; §4 rendering fixtures |
| 055 (behavior eval harness) | §2 graded cases; §4 platform-wide injection-resistance category |
| 056 (context compaction) | §2(c) summary laundering; §3 extraction-not-obedience prompt; §4 hostile span |
| 059 (sandboxed code execution) | §2(d) file-to-code channel; §3 helper prompt framing; §4 hostile CSV |
| 072 (sandbox egress) | Adjacent enforcement for §2(d); provider egress verification remains outside this note's framing contract |
