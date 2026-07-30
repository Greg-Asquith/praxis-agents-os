# Security and dependency maintenance plans

These plans replace six Dependabot pull requests closed on 2026-07-30. The
updates will be applied locally in small, ordered units so failures can be
attributed to one dependency change rather than a mixed bot branch.

This is a maintenance runbook, not a new product-roadmap lane. Do not add these
local plan numbers to `docs/plans/000_MASTER_ROADMAP.md`.

## Execution rules

1. Start from a clean, current `main`. Preserve unrelated working-tree changes.
2. Restore a green baseline before changing dependencies. As of 2026-07-30,
   main fails
   `test_hostile_gmail_content_is_enclosed_by_dispatch`; resolve and land that
   independently before executing plan 001.
3. Execute one plan at a time in the order below. Do not begin the next plan
   until the current plan's local checks pass.
4. Keep action references pinned to full commit SHAs and package-manager
   lockfiles deterministic.
5. Do not use `npm audit fix --force`, broad `uv lock --upgrade`, or broad
   `pnpm update`; update only the packages named by the active plan.
6. Do not create commits or push without explicit human approval. When approval
   is given, keep each plan as an independently reviewable commit unless the
   operator requests a different history.
7. After a pushed change is green in CI, update its status here before starting
   the next plan.

## Ordered tracker

| Plan | Change | Risk | Status |
| --- | --- | --- | --- |
| [001](001-actions-setup-node-v7.md) | `actions/setup-node` 6.4.0 → 7.0.0 | Low | TODO |
| [002](002-actions-setup-uv-v9.md) | `astral-sh/setup-uv` 8.2.0 → 9.0.0 | Low–medium | TODO |
| [003](003-markitdown-0.1.7.md) | MarkItDown floor 0.1.6 → 0.1.7 | Low | TODO |
| [004](004-web-minor-patch-refresh.md) | Web minor/patch refresh | Medium | TODO |
| [005](005-api-minor-patch-refresh.md) | API minor/patch refresh | High | TODO |
| [006](006-node-26-alignment-deferred.md) | Node 26 runtime and type alignment | Medium | DEFERRED |

## Closed Dependabot pull requests

- #1 `astral-sh/setup-uv` 9.0.0
- #2 `actions/setup-node` 7.0.0
- #3 API minor/patch group
- #4 MarkItDown 0.1.7
- #5 web minor/patch group
- #6 `@types/node` 26.1.2

All six were closed with an explanation that the changes would be applied and
verified locally.

## Unrelated to this runbook

[010-frontend-audit-hardening.md](010-frontend-audit-hardening.md) is a
defect-remediation list from a 2026-07-30 frontend security audit. It shares
this directory but not this runbook's ordering or execution rules.
