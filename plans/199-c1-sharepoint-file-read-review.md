# Plan 199 C1: SharePoint file-read review

## Outcome and scope

**Review complete, 15 September 2026. All four findings are fixed.** Two concern
decoding, one concerns truncation status, and one concerns missing citations.
No critical or high-priority security defect was confirmed. The original passing
tests omitted the reproduced edge cases below; the fixes add regression coverage.

The review covers the uncommitted C1 implementation on commit
`8d41176615da4b769747afa09d1d8e931fb4c215`, including new files. It uses
[REVIEW.md](../REVIEW.md), the [parent plan](../docs/plans/199-sharepoint-file-tools.md),
and the [C1 completion record](../docs/plans/complete/199-c1-sharepoint-file-read.md).
Before implementing fixes, compare the cited code with the live worktree:
the commit alone does not identify the uncommitted implementation.

Source code was reviewed without edits. No commits, live provider calls, or
live model calls were made. The finding list is exhaustive for issues confirmed
in this review, not a claim that every possible defect has been excluded.

The reviewed surface includes SharePoint operations, tool registration,
settings, schemas, context targeting, audit dispatch, the shared Graph download
client, logging filters, document conversion, new fixtures, runtime scenarios,
and owning documentation. Shared converter callers were checked for compatibility.
C2 presentation, D1/D2 link resolution, document editing, and Knowledge Base
import remain separate planned work. Their absence is not a C1 defect.

## Finding register

P2 means a correctness or implementation issue to fix in this slice. P3 means
a smaller correctness or defensive-validation issue. All four belong in the
C1 closure list. S means a small change, including focused tests. Risk describes
the fix, not the present defect.

| ID | Priority | Finding | Origin | Effort | Fix risk | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | P2 | Move strict decoding inside the conversion worker | Introduced | S | Medium | Closed |
| R2 | P2 | Reject undecodable HTML consistently | New C1 contract over an existing permissive helper | S, shared with R1 | Medium | Closed |
| R3 | P3 | Return actual truncation state | Introduced by copying an existing Outlook pattern | S | Medium | Closed |
| R4 | P3 | Require a citation before reading file content | New C1 use of an existing permissive projection | S | Low if scoped to reads | Closed |

The evidence in R1-R4 describes the reviewed implementation before fixes.
Post-fix evidence appears in the closure record at the end of this document.

### R1: Move strict decoding inside the conversion worker

**Evidence:** `apps/api/integrations/sharepoint/operations/convert_item.py:21`
calls `data.decode("utf-8")` synchronously and discards the result. The helper
decodes the same bytes again at `apps/api/utils/document_markdown.py:84`.
Its deadline begins at `document_markdown.py:61`, after the first decode.
`apps/api/integrations/sharepoint/settings.py:16` permits up to 100 MiB.

Every accepted plain-text, Markdown, CSV, or JSON file incurs an extra full
decode and allocation on the event loop. That work cannot yield to cancellation
and sits outside the conversion deadline. The classification is also copied at
`convert_item.py:45` and `document_markdown.py:15`, creating a maintenance risk.
This is a confirmed execution-path issue. No production outage or memory
exhaustion was observed.

**Fix:** Make strict decoding an explicit shared-converter input and perform it
inside the worker. Preserve the existing default for callers that use replacement
decoding. Use one shared classification for decoding and conversion source.
Do not add another caller-side pre-decode or format list.

**Acceptance evidence:** Add a deterministic test proving the caller does not
decode file bytes before worker dispatch. Exercise invalid UTF-8 through the
real process path, retain timeout/cancellation PID checks, and verify unchanged
replacement behaviour when strict decoding is omitted.

**Confidence:** High. **Dependencies:** Resolve with R2. Coordinate the shared
helper interface with R3 so it changes once. **Risk:** Changing decoding defaults
globally could break Outlook, Files, skills, and Knowledge Base imports.

### R2: Reject undecodable HTML consistently

**Evidence:** `convert_item.py:21` excludes `text/html` from strict decoding.
The shared file contract accepts HTML at `apps/api/services/files/contract.py:71`.
`document_markdown.py:122` replaces invalid bytes before HTML conversion.
The [Microsoft Graph reference](../docs/implementation/integrations/microsoft-graph.md)
states that invalid UTF-8 text reports `conversion_failed`.

A local probe through the real conversion worker supplied malformed HTML.
The operation succeeded with a replacement character in the returned Markdown.
Corrupt text is therefore silently changed instead of producing C1's documented
failure. Existing tests cover undecodable plain text and corrupt DOCX, but omit
HTML in `apps/api/tests/integrations/sharepoint/test_file_content.py:161`.

**Fix:** Apply SharePoint's strict decoding policy to supported HTML inside the
worker introduced by R1. Keep valid HTML as `source="converted"`. Preserve
existing permissive decoding for unrelated callers.

**Acceptance evidence:** Add valid and invalid HTML cases using the real worker.
Invalid HTML must return `conversion_failed` with safe recovery copy. Check the
same code in the public failure and operation audit. Valid HTML must retain its
Markdown, citation, and untrusted provenance. Existing plain-text, Office, and
Outlook tests must continue to pass.

**Confidence:** High. **Dependencies:** R1. **Risk:** A global HTML decoding
change would alter other converter consumers. The permissive shared behaviour
predates C1; this finding concerns its conflict with C1's promised policy.

### R3: Return actual truncation state

**Evidence:** `convert_item.py:43` uses
`markdown.endswith(TRUNCATION_MARKER)`. At `document_markdown.py:130`, the
bounded helper returns under-limit content unchanged. Outlook uses the same
inference at `apps/api/integrations/outlook_mail/operations/get_attachment.py:83`.

A complete 70-byte plain-text document ending with the literal marker passed
through the real worker unchanged, but returned `truncated=True`. This gives
the model and C2 presenter incorrect information about whether content was lost.

**Fix:** Return actual truncation metadata from the bounding operation. Carry
that state through a small shared conversion result or companion entry point.
Keep string-returning callers working deliberately. Do not infer state from
text length or marker presence elsewhere.

**Acceptance evidence:** Complete content containing or ending with the literal
marker reports `false`. Actual ASCII and multibyte truncation reports `true`.
Output stays within 65,536 UTF-8 bytes, including the marker. The result must
cross the process boundary and retain the existing public tool schema.

**Confidence:** High. **Dependencies:** Coordinate with R1/R2's helper changes.
**Risk:** Replacing the helper's return type without updating callers would
break Files, skills, Knowledge Base, extraction jobs, and native code results.
Outlook's existing false-positive behaviour is an affected sibling, not a new
regression caused by C1. A shared fix should explicitly decide how to handle it.

### R4: Require a citation before reading file content

**Evidence:** `download_item.py:23` projects metadata without requiring a
citation. `apps/api/integrations/sharepoint/operations/utils.py:83` converts
missing or non-string text to an empty string. `utils.py:98` only rejects
excessive citation length. `convert_item.py:41` returns the resulting value.

A local probe with `webUrl=None` produced successful content with
`web_url=""`. The output schema accepts it. C1 promises a citation link, so
incomplete provider metadata can produce a successful read that cannot be cited.
The conditional behaviour is confirmed. No evidence shows ordinary Graph
responses omitting this field, so production frequency is unverified.

**Fix:** Require a non-empty, usable HTTP(S) citation in C1 metadata validation
before downloading bytes. Fail safely without echoing the rejected value. Keep
the full valid URL within the existing 8,192-character boundary. Avoid changing
listing/search metadata optionality as a side effect.

**Acceptance evidence:** Absent, null, non-string, empty, and unusable citations
fail before `get_bytes`. Valid long citations survive unchanged. Preserve
`sharepoint_drive_item` provenance, listing/search behaviour, and URL secrecy.

**Confidence:** High for the conditional defect. **Dependencies:** Independent
of conversion fixes. **Risk:** Low when scoped to C1; tightening the common
projection would also change earlier slices.

## Cross-reference and execution order

Use the following order to keep fixes from undoing one another:

| Order | Work | Interaction to preserve |
| --- | --- | --- |
| 1 | Add regression cases for R1-R4 | Confirm they expose the recorded behaviour before fixing it. Use the existing Graph fixture, audit helper, and real process tests. |
| 2 | Resolve R1 and R2 together | Decode once inside the worker. Strictness and format classification must have one owner. Retain other callers' defaults. |
| 3 | Resolve R3 using the agreed conversion interface | Return serialisable truncation state from the same worker operation. Preserve public output fields and 64 KiB limits. |
| 4 | Resolve R4 in read-specific metadata validation | Reject missing citations before bytes. Keep signed URLs internal and earlier listing/search behaviour stable. |
| 5 | Run all closure checks and update owning docs | Update C1's completion evidence only after the new regression cases pass. Keep C2 and D pending. |

The converter is shared by these consumers. Include their tests if its interface
or defaults change:

- `integrations/outlook_mail/operations/get_attachment.py`
- `services/files/attachment_text.py`
- `services/jobs/handlers/extract_file_markdown.py`
- `services/jobs/handlers/extract_platform_file_markdown.py`
- `services/skills/documents/utils.py`
- `services/kb/utils.py`
- `services/agents/runtime/tools/native/run_code_file_bridge.py`

Paths in this list are relative to `apps/api`. Keep provider-specific error copy
and provenance in SharePoint operations. Keep generic conversion mechanics in
`utils/document_markdown.py`. No cross-provider imports, new storage, schema
changes, widened grants, or frontend work are needed for these findings.

## Requirement audit

The following evidence maps C1's scope to the implementation and verification:

| Requirement | Evidence inspected | Assessment |
| --- | --- | --- |
| Registered read-only, automatic, provider-query tool; typed output; 90-second timeout; Code Mode eligibility | `tools/read_file.py`, `tools/__init__.py`, provider manifest, contract matrix, complete catalogue stub tests | Verified |
| Exactly one selected drive before credentials; no remote or foreign-drive reads | `run_context_targets`, credential seam, `get_item`, rejected-metadata and ambiguous-selection tests | Verified |
| Supported documents and text through the shared contract | `download_item`, document contract, real DOCX/XLSX tests and shared PDF/Office fixtures | Verified; R2 adds strict HTML failure coverage |
| Metadata and streamed download caps; configurable default of 50 MiB | Settings and overflow tests with missing/understated Content-Length | Verified |
| No bearer token, redirects, private-address access, or signed URL in results/errors/logs/audits | Graph client, installed HTTP logger names, download/filter tests, saved runtime results | Verified for inspected paths and tests |
| Bounded and cancellable conversion | AnyIO process call, real worker PID tests, in-worker bounding and single decoding checks | Verified after R1 |
| Name, type, actual byte size, modified time, citation, Markdown, source, and truncation status | Schema, real conversion and Unicode tests, literal marker and citation regressions | Verified after R3 and R4 |
| Safe failure codes and recovery copy | Unsupported type, size, corrupt text/HTML/Office, 403/404/423/timeout tests and audit checks | Verified after R2 |
| Framed hostile content through direct and Code Mode dispatch | Hostile DOCX, shared enclosure tests, database-backed file-read scenarios | Mechanical enclosure verified; no live-model resistance claim |
| Package independent of Outlook settings/packages | Provider loader tests and package import-law tests | Verified |
| Owning documentation and threat model updated | Graph/storage references, packaging note, threat model, API guidance, C1 notes | Updated with final decoding, truncation, and citation contracts |
| Maintainable structure and reasonable complexity | One operation/tool per module, shared runners, Ruff and C901 checks | Verified; worker owns decoding and source classification |

## Verification performed before fixes

The primary review run passed **535 tests with no skips**. A separate run of
file extraction, platform extraction, attachment text, and skill-document tests
passed **49 tests**. These two runs cover distinct test files. Independent
reviewers also ran overlapping focused suites; those counts are not added here.

The exact primary command, run from `apps/api`, was:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run --no-sync pytest tests/integrations/sharepoint tests/integrations/test_integration_tools.py tests/integrations/test_fetched_content_enclosure.py tests/contract/test_integration_import_laws.py tests/services/integrations/test_manifest_loader.py tests/integrations/outlook_mail tests/scenarios/test_sharepoint_file_read.py tests/scenarios/test_sharepoint_folder_listing.py tests/services/integrations/test_microsoft_graph.py tests/services/integrations/test_microsoft_graph_downloads.py tests/services/integrations/test_graph_download_logging.py tests/utils/test_document_markdown.py tests/utils/test_document_markdown_office.py tests/utils/test_document_conversion_process.py tests/services/agents/runtime/code_mode/test_stubs.py -q --tb=short
```

The additional caller regression command, also from `apps/api`, was:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run --no-sync pytest tests/services/files/test_extract_file_markdown.py tests/services/files/test_extract_platform_file_markdown.py tests/services/files/test_attachment_text.py tests/services/skills/test_skill_documents.py -q --tb=short
```

These checks also passed:

```bash
# From apps/api
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ruff check integrations/sharepoint utils/document_markdown.py services/integrations/microsoft_graph/download_logging.py --select C901 --config 'lint.mccabe.max-complexity=8'

# From the repository root
python3 .github/scripts/dependency_audit.py api
git diff --check
```

The dependency audit reported no known vulnerabilities. The initial sandboxed
pytest/probe commands failed on uv cache access; their reruns succeeded with
the required environment access. No dependencies were changed by the review.

Full `make check`, frontend checks, migration drift checks, live tenant/model
tests, production-container execution, and full KB/native-tool integration
suites were not run. The change adds no frontend code or database schema.
The real parser probes used tiny local inputs and mocked provider downloads.
They establish the reported behaviour, not production frequency or load limits.

## Considered, rejected, and inherited observations

The following observations avoid duplicate or unsupported findings:

- **Signed URL leakage, redirects, and drive escape:** no confirmed defect.
  The annotation is removed before conversion, production downloads use a
  separate unauthenticated client, and the task-local filters match the installed
  HTTPX2/HTTPCore2 loggers. Keep those tests when changing either seam.
- **Process timeout leaves the parser running:** rejected. Existing real PID
  tests prove termination on timeout and cancellation. AnyIO documents worker
  cancellation as process termination in its [worker-process reference](https://anyio.readthedocs.io/en/stable/subprocesses.html#running-functions-in-worker-processes).
- **A new converter framework or cross-provider abstraction is needed:**
  rejected. The opt-in worker and shared Graph seam fit the existing design.
  R1-R3 need a focused extension to the existing helper.
- **Other converters must switch to processes in C1:** rejected. Their thread
  execution is explicitly retained by the slice. Compatibility tests remain
  necessary because the common synchronous conversion body changed.
- **Parser memory exhaustion:** unproven. Installed AnyDoc metadata documents
  decompression, nesting, node, expansion, and retained-asset limits. No safe
  probe established an exhaustion defect. Output and wall-clock limits are
  verified; this is not a claim of operating-system memory isolation.
- **Shared truncation with an extremely small cap:** an inherited helper issue
  exists at `document_markdown.py:133`: when the cap is shorter than the marker,
  the helper still returns the full marker. C1 always uses 65,536 bytes, so this
  is not a C1 closure blocker. If R3 changes the generic bounding contract,
  cover small caps deliberately rather than accidentally preserving the bug.
  The fix covers zero, small, marker-sized, and 64 KiB caps and rejects negative
  caps. Even a partial marker stays within the byte limit.
- **Outlook/skill marker inference:** inherited. Outlook checks the suffix and
  `services/skills/documents/get_document_markdown.py:52` checks marker presence.
  R3 must account for these callers, but a wider stored-document metadata
  migration is outside this slice.
  Outlook reads now use actual conversion metadata. Skill document reads retain
  the stored Markdown contract and its inherited marker inference; migrating
  persisted skill-document metadata remains outside C1.
- **Citation metadata validation:** R4 is a defensive contract gap, not a
  demonstrated Microsoft Graph outage. Keep that distinction in prioritisation.
- **Downloading through the annotation rather than `/content`:** correct.
  Microsoft's [download contract](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)
  documents the annotation and says the pre-authenticated URL requires no
  Authorization header. No new write grant is needed for C1.
- **Pending C2/D/editing/import workflows:** intentional scope boundaries,
  not missing C1 implementation.

## Closure checklist

Complete these steps before describing C1 as closed after review:

- [x] R1: strict decoding occurs once inside the cancellable worker.
- [x] R2: invalid HTML fails with `conversion_failed`; valid HTML still converts.
- [x] R3: truncation reflects actual bounding, including literal-marker cases.
- [x] R4: unusable citations fail before file download.
- [x] Each regression case fails against the reviewed implementation and passes
  after its fix. Record any intentionally rejected finding with evidence here.
- [x] The primary regression suite, additional converter-caller tests, lint,
  formatting, focused complexity check, and diff check pass after the fixes.
- [x] Shared-helper signature/default changes have corresponding caller checks,
  including KB/native consumers if those paths change.
- [x] Docs describe the final decoding/truncation contract, and the C1 completion
  record includes actual post-fix results. C2 and D remain marked pending.

This review does not authorise source implementation or Git commits. It provides
the issue list and the evidence needed to review their eventual fixes together.

## Post-fix closure record

The subsequent request to action every finding authorises these source fixes.
No finding was rejected and no Git commit was created.

The regression evidence is recorded as follows:

| Finding | Failure reproduced before the fix | Passing evidence after the fix |
| --- | --- | --- |
| R1 | The caller-decode guard raises at `convert_item` before worker dispatch. | The guard reaches dispatch. Real-worker byte probes reject caller-process decoding and a second decode. Strict failures and permissive defaults cover all six shared text/HTML types. Existing timeout and cancellation PID tests pass. |
| R2 | Invalid HTML succeeds in both the operation test and public tool/audit test. | Invalid HTML reports `conversion_failed` in the public result and operation audit, with safe recovery copy. Valid HTML retains converted Markdown, citation, and provenance through direct and Code Mode scenarios. |
| R3 | Complete literal-marker suffixes report `true` in SharePoint and Outlook. | Both providers use `DocumentConversionResult` from the shared bounding operation. Literal markers remain complete, ASCII/multibyte output stays within 65,536 bytes, and actual truncation reports `true`. Direct and Code Mode saved results preserve `false` for literal-marker content. |
| R4 | The citation suite reports 20 failures and seven passing controls before validation. | All 27 citation tests pass, covering rejection before download, URL secrecy, full 8,192-character HTTP(S) links, provenance, and unchanged optional listing/search citations. |

The primary regression command in this review passed **593 tests with no skips**.
The file-read scenario then gained four additional HTML/literal-marker variants.
The following compatibility command passed **313 tests with no skips**, including
all six final direct/Code Mode file-read scenarios. Two scenarios overlap the
primary run, so the two runs cover **904 distinct cases**:

```bash
# From apps/api
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run --no-sync pytest tests/services/files/test_extract_file_markdown.py tests/services/files/test_extract_platform_file_markdown.py tests/services/files/test_attachment_text.py tests/services/skills/test_skill_documents.py tests/services/kb/test_fetch_url.py tests/services/agents/runtime/test_native_tools.py tests/scenarios/test_sharepoint_file_read.py -q --tb=short
```

Backend Ruff lint and formatting pass. The focused C901 check passes with a
maximum complexity of eight for SharePoint, the converter, download logging,
and Outlook attachment reads. The dependency audit reports no known
vulnerabilities. `git diff --check` passes. A separate read-only final review
found no remaining R1-R4 defect.

The Graph and storage references, packaging note, and C1 completion record
describe the final contracts. C2, D, and editing/import workflows remain pending.
No frontend, database schema, or dependency changed during these fixes. Full
`make check`, live provider/model calls, and deployment remain outside this
focused verification. The existing worker tests establish cancellation and
bounded output, not operating-system memory isolation.
