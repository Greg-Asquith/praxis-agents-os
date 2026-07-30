# Plan 003: Raise the MarkItDown floor to 0.1.7

## Status

- **Priority:** P2
- **Risk:** LOW
- **Status:** READY FOR REVIEW — local gate passed; remote verification awaits an approved push
- **Depends on:** Plan 002
- **Source:** Closed Dependabot PR #4

## Intent

Permit MarkItDown 0.1.7 for document extraction. The release contains focused
PPTX chart, SVG fallback, and equation-conversion fixes.

## Fixed decisions

- Change only
  `markitdown[docx,pdf,pptx,xlsx]>=0.1.6` to `>=0.1.7`.
- Regenerate `apps/api/uv.lock` for this package only.
- Do not upgrade unrelated direct dependencies during locking.
- Exercise real representative document conversions in addition to mocked
  service tests when fixtures are available.

## Scope

- `apps/api/pyproject.toml`
- `apps/api/uv.lock`
- Tests only if the new release exposes an actual compatibility defect.

## STOP conditions

Stop and report if:

- uv changes unrelated direct-dependency floors;
- document extraction requires application-code changes beyond a narrow
  compatibility correction;
- DOCX, PDF, PPTX, or XLSX conversion regresses;
- database-backed extraction tests fail for a reason not present on the green
  baseline.

## Steps

1. Change the MarkItDown lower bound only.
2. Run a targeted lock update for MarkItDown and inspect the lockfile diff.
3. Run the skill-document and file-extraction tests.
4. Run the complete API gate.
5. After an approved push, require a fully green CI run before continuing.

## Verification

```bash
cd apps/api
uv lock --upgrade-package markitdown
uv run pytest \
  tests/services/skills/test_skill_documents.py \
  tests/services/files/test_extract_file_markdown.py
uv run ruff check .
uv run ruff format --check .
cd ../..
make check
```

## Completion criteria

- The declared floor is 0.1.7.
- The lockfile resolves the intended release without unrelated direct upgrades.
- Focused extraction tests and `make check` pass.
