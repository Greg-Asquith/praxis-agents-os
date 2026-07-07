# Plan 072: Sandbox egress must be probed, not assumed (amendment to 059)

> **Executor instructions**: This is an amendment plan in the 061 mold —
> its deliverable is the amendment block drafted verbatim below, appended
> to `docs/plans/059-sandboxed-code-execution.md`, not code. The code
> lands through the amended 059. When done, update the status row in
> `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/059-sandboxed-code-execution.md`
> Confirm 059's status row in `docs/plans/000_README.md` is still TODO and
> that its decision 2 and Step 1 read as excerpted under "Current state".
> If 059 has started executing, or its classification text has changed,
> STOP — reconcile against the landed code instead of amending the plan.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW as a doc; it prevents an unattended-exfiltration
  misclassification before any code-execution code exists
- **Depends on**: 059 (written, TODO), 054 (`effect_scope` vocabulary).
  **Binds before 059 executes** — the amendment gates 059's Step 1 and
  its decision 2 classification
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07

## Decisions taken

1. **059's classification is conditional, and the condition is currently
   unverified.** 059 decision 2 classifies `run_code` as
   `effect="write"` + `effect_scope="internal"`, default `approval`,
   `supports_auto=True`, and states the consequence explicitly:
   "`internal` scope means scheduled runs may run code without human
   approval *if* the agent policy is `auto`". That is only sound if the
   sandbox genuinely "cannot mutate external systems (that is the
   point)" — which depends on per-provider network egress posture that
   059 never checks. Anthropic's code-execution container is documented
   as network-isolated; OpenAI's and Google's sandbox capabilities vary
   and change over time. The classification must be gated on an observed
   fact, not a design assumption.
2. **Egress posture becomes a recorded Step 1 probe.** 059's Step 1
   probes (a)–(c) cover API mechanics only: capability acceptance and
   result-part shapes, audit visibility of helper-run native parts, and
   file-output capture. A new probe (d) executes code in each provider's
   sandbox that attempts outbound access (DNS + HTTP to a canary) and
   records the observed posture per provider in the module-docstring
   probe notes, dated.
3. **A provider with ANY egress cannot hold the `internal` grant.** If a
   sandbox can reach the network, `run_code` on that provider is an
   unattended exfiltration primitive: poisoned file content steers the
   generated code into encoding workspace data as outbound requests, and
   under `internal` + `auto` no human is in the loop. In 054 vocabulary
   that provider's `run_code` is an external-effect write. But 054 puts
   `effect_scope` on the `RuntimeToolDefinition` — one
   `Literal["internal", "external"]` per definition, no per-provider
   axis — so the honest v1 is an allowlist, not a scope split: **only
   egress-isolated providers may be enabled for `run_code`**, enforced
   where 059 decision 7 already validates the `model_provider` argument;
   unverified providers are rejected until a per-provider scope
   mechanism exists.
4. **Egress posture is externally mutable, so it is re-verified.**
   Providers change sandbox capabilities without notice. Probe (d) is
   re-run on any pydantic-ai upgrade or provider SDK/API version bump
   touching code execution; the dated posture record is refreshed in the
   module docstring and mirrored in the governance §2 row.
5. **The canonical attack gets a scenario.** A poisoned input file
   steering generated code toward exfiltration is the textbook attack on
   code-interpreter tools. The 055 harness gains a fixture + scenario
   asserting the boundary with a scripted helper (live LLM calls are
   blocked in tests, per 059's own test plan); live egress behavior is
   pinned by probe (d) and the manual smoke, mirroring how 059 pins all
   live behavior.

## Why this matters

059 is the first tool that ships workspace file content into
third-party compute and executes model-generated code against it —
unattended, on scheduled runs, when an editor sets the policy to `auto`.
That is exactly the configuration 059 calls "the intended behavior for
scheduled data digests". The design is right *if* the sandboxes are
egress-isolated; it is an exfiltration channel if any of them is not.
Verifying the isolation costs one probe per provider now; discovering it
after launch costs an incident. Amending 059 before it executes is free.

## Current state

All anchors verified on the working tree at `c770a1c` (2026-07-07).

- **059 is written, TODO** (`docs/plans/000_README.md` row 059; no
  `run_code` code exists — `services/agents/runtime/tools/native/`
  contains `web_search.py` only).
- **The classification being amended** — 059 decision 2, verbatim:
  "**Classification: `effect="read"` is wrong; `effect="write"` +
  `effect_scope="internal"`, default policy `approval`,
  `supports_auto=True`.** The sandbox cannot mutate external systems
  (that is the point) […] Envelope note (054): `internal` scope means
  scheduled runs may run code without human approval *if* the agent
  policy is `auto` — that is the intended behavior for scheduled data
  digests."
- **059 Step 1 probes are API-mechanics only**: (a) provider acceptance
  of `NativeTool(CodeExecutionTool())` and result-part shapes, (b)
  native call/return part visibility in helper result messages, (c)
  per-provider file-output shape. No network probe. Decision 5 ("police
  the boundary") enumerates the boundary controls — file gates, policy,
  audit, output bounding — and egress posture is absent from the list.
- **054's contract cannot express per-provider scope**:
  `effect_scope: Literal["internal", "external"]` is a field on
  `RuntimeToolDefinition` (054 decision 1) — per definition, not per
  provider or per call. 054 is itself TODO; nothing here changes it.
- **The enforcement seam already exists in 059**: decision 7 validates
  the per-call `model_provider` argument against a supported set (the
  `web_search` mechanics) — the natural choke point for an
  egress-verified allowlist, with no new machinery.
- **055 harness**: deterministic scenarios via `FunctionModel`-scripted
  helpers under `tests/scenarios/`; live LLM calls are blocked in tests.

## Scope

**In scope:**

- The amendment block below, appended verbatim to
  `docs/plans/059-sandboxed-code-execution.md`
- `docs/plans/000_README.md`: row for 072; note on 059's dependency line

**Out of scope:**

- Any code. The probe, allowlist enforcement, docstring posture record,
  and scenarios land inside 059's execution per the amendment.
- Changes to 054 or to the `effect_scope` contract (a per-provider scope
  axis is a possible future plan, not this one).
- External sandbox vendors (059 decision 6) — covered by a maintenance
  note, not new text in 059.

## Git workflow

- Branch: `advisor/072-sandbox-egress-verification`
- Commit: `Docs - Sandbox Egress Verification Amendment`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

1. Run the drift check; re-verify the "Current state" excerpts against
   059's live text.
2. Append the amendment block below to the end of
   `docs/plans/059-sandboxed-code-execution.md`, verbatim.
3. Update `docs/plans/000_README.md`: add the 072 row (Lane B), and
   append "amended by 072 (egress verification)" to 059's row notes.

## Amendment text (append to 059 verbatim)

```markdown
## Amendment: sandbox egress verification (plan 072, 2026-07-07)

Binding on execution. Decision 2's `effect_scope="internal"` +
`supports_auto=True` classification silently assumes every enabled
provider's sandbox has no network egress. That is a per-provider,
externally mutable fact — probe it, gate on it, and re-check it.

1. **Step 1 gains probe (d): egress posture.** For each catalog
   provider, run a helper turn whose task has the sandbox attempt
   outbound access: DNS resolution of a unique canary hostname and an
   HTTP request to an operator-controlled canary URL. Record per
   provider, dated, in the module-docstring probe notes: whether DNS
   resolves, whether the HTTP request lands (canary hit), and the error
   surface when blocked. Vendor documentation is not a probe result.
2. **Classification gates on probe (d).** A provider whose sandbox shows
   ANY egress (DNS or HTTP) cannot carry the `internal` classification —
   for that provider `run_code` is an external-effect write (054
   vocabulary) and must not run unattended. Because `effect_scope` is
   per-definition, v1 does not split the scope: the decision 7 supported
   set becomes the **egress-verified set**, and a `model_provider`
   naming an unverified provider is rejected at validation time with an
   explicit error. Do not classify the definition `external` for
   everyone instead — that would put scheduled digests behind approval
   on providers that earned `internal`.
3. **Re-verification rule.** Re-run probe (d) on any pydantic-ai upgrade
   or provider SDK/API change touching code execution; refresh the dated
   posture record in the module docstring and mirror it in the
   governance §2 row this plan updates. A provider that loses isolation
   leaves the verified set in the same change.
4. **Test-plan delta (055 scenarios).** Add: (a) a poisoned-input
   fixture — a CSV whose cell content instructs exfiltration of the
   other rows to a URL — driven through a scripted helper emitting
   exfiltration-shaped code, asserting the boundary controls (audit
   rows, output bounding, and rejection of unverified providers); (b) a
   validation test that an unverified `model_provider` is rejected. Live
   egress cannot be asserted in tests (live LLM calls are blocked); it
   is pinned by probe (d), and the Step 4 manual smoke must include the
   poisoned CSV producing no canary hit on any verified provider.

Additional STOP condition: probe (d) shows egress on all three
providers — `run_code` has no enableable provider and needs the operator
before anything ships.
```

## Done criteria

- [ ] `docs/plans/059-sandboxed-code-execution.md` ends with the
      amendment block above, character-for-character
- [ ] `docs/plans/000_README.md` has a 072 row and 059's row notes the
      amendment
- [ ] No code changed; no other plan file changed

## STOP conditions

- 059 has started executing or is DONE — amend nothing; audit the landed
  `run_code` against decisions 1–4 above and report instead.
- 059's decision 2 or Step 1 no longer matches the "Current state"
  excerpts — reconcile before appending.
- 054 has grown a per-provider or per-call `effect_scope` mechanism —
  the allowlist workaround in decision 3 may be obsolete; reconcile the
  amendment text with the real contract first.

## Maintenance notes

- When external sandbox executors arrive (059 decision 6), probe (d) is
  a precondition for enabling each one — same rule, same recording
  places.
- If a future plan adds per-provider `effect_scope`, migrate the
  allowlist gate to real scope classification in the same change.
- Reviewers of 059's execution should scrutinize: probe (d) results
  dated and per-provider, the verified set enforced at the decision 7
  validation seam (not documentation), and the poisoned CSV smoke run
  against every enabled provider.
