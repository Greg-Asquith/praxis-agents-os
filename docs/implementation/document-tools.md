# Document tools

Document tools read, edit, and create `.pptx`, `.xlsx`, and `.docx` Files with
`python-pptx`, `openpyxl`, and `python-docx`. Office files are
attacker-controlled input, so every library call runs in a bounded worker
process, never in the API or worker process itself.

Status: the hardened worker runtime, the read tools, the edit and create
tools, and their conversation rows are implemented. The bundled default
templates are pending review by a layout designer.

## Read tools

The read tools are registered in `services/agents/runtime/tools/documents/`.
They're auto-mounted, deferred until tool search loads them, read-only, and
have no egress. Every tool except `view_document_image` can be called from a
Code Mode script. The tools are as follows:

| Tool | Returns |
| --- | --- |
| `read_presentation(file_id, slides?)` | Slide size and per slide: id, layout, background images, shapes (id, name, kind, placeholder, position in points, paragraphs, table cells, chart series with x values and bubble sizes where present, image references), and notes. The first page, without `slides`, adds layouts with their placeholders and external links |
| `read_workbook(file_id, sheet?, range?, cursor?)` | The non-empty cells of one sheet with value, formula, number format, and `calculated`. The first page, without `cursor`, adds the sheet list, external links, and the chosen sheet's outline: dimensions, tables, merged ranges, freeze panes, charts, and image references |
| `read_word_document(file_id, start?, limit?)` | Body blocks in order: paragraphs (index, style, directly set list level, text, spans, image references), tables, and content controls, each with image references. The first page, without `start`, adds paragraph styles, headers and footers per section and variant, comments, and external links. Every page says whether tracked changes exist in any story |
| `read_table(file_id, sheet?, range?, list_name?, offset?, limit?)` | Columns, rows as dictionaries, and `total_rows`, from an `.xlsx` sheet, a UTF-8 CSV or TSV file, or a saved tool result. Workbook formulas with no saved value come back as `None` and are named in `uncalculated_cells` |
| `view_document_image(file_id, image_ref)` | One embedded image as image content, for models that support vision |

`read_document` is the Knowledge Base tool, so the Word reader is
`read_word_document`.

Each tool loads the conversation's visible revision of the File through the
same helper as `read_file`, so another workspace's File reads as not found.
Every result starts with `file_id`, `revision_id`, and `name`.

### Untrusted text

Text from a file comes back as untrusted-content nodes whose `source_ref` is
`file:FILE_ID/revision:REVISION_ID`. That covers paragraph and cell text,
formulas, notes, comments, headers, footers, chart labels, CSV values, and
external link targets.
Names and identifiers that edits target, such as sheet, layout, style, and
shape names, stay plain strings capped at 100 characters. Numbers, booleans,
and dates stay plain values, so scripts can do maths on them. A script that
reads document text is tainted, as described in
[untrusted data in Code Mode](../architecture/code-mode.md#untrusted-data-whole-interpreter-taint).

### Paging

Each read returns at most `DOCUMENT_TOOLS_READ_MAX_CHARS` characters, measured
after framing, with 1,000 characters kept for keys, cursors, and the File
fields. A result carries the next position when more remains: `next_slide` for
decks, `next_cursor` (a row number) for workbook cells, `next_start` for Word
blocks, and `next_offset` for tables.

Metadata, such as layouts, the sheet list and outline, styles, headers,
footers, comments, and external links, comes only on the first page. It uses
the budget first and says `*_truncated` when it doesn't all fit. When the first
slide, row, or block doesn't fit beside that metadata, the page ends before it
and the next page, which has no metadata, returns it. A single slide, row, or
block larger than a whole page is refused with a message naming the cursor
that skips it, so no text is cut or silently dropped. In Code Mode the budget
also stays under `AGENT_CODE_MODE_VALUE_MAX_BYTES` at the default settings,
even for four-byte characters.

### Streaming workbook reads

`read_workbook` and `read_table` open `.xlsx` files with openpyxl's read-only
mode, reading the formula view and the cached-value view in step. Cell rows are
parsed on demand, but openpyxl still loads the whole shared-string table and
the styles before streaming, so a string-heavy workbook can reach the worker
memory limit during a read. That fails closed like any other worker memory
error. `read_table` keeps counting rows after a page fills, to report
`total_rows`, and each page starts from the top of the sheet again.
Read-only worksheets don't load sheet metadata, so the worker streams the
chosen sheet part, cuts out `sheetData`, and parses what's left with
`defusedxml`, along with the relationship, table, and drawing parts.

Measured on Linux with a 384 MiB worker limit, a 100,000-row, 10-column
numeric workbook that a full load can't open under that limit reads a page
and counts every table row.

### Tables and saved results

`read_table` parses CSV, TSV, and JSON in the document worker too, so a large
upload can't block the API process's event loop or use its memory. CSV and TSV
must be UTF-8; invalid bytes and fields over 131,072 characters are refused.
Plain numbers become numbers; values with leading zeros or separators, and
numbers too large for a float, stay text. JSON with `NaN`, `Infinity`, or an
overflowing number is refused.

For a JSON File, `list_name` is a key from a saved result preview's `lists`,
such as `results.0.data.rows`. A list under a key that contains a dot can't be
addressed. Object keys stay plain strings capped at 100 characters, and an
object whose keys share their first 100 characters is refused rather than
merged.

Only the first revision of a retained tool result (`File.is_tool_result`)
keeps the untrusted-content nodes its source tool framed, and only nodes with
exactly the node fields as strings. Every other JSON File, including an upload
that contains node-shaped objects, is framed as File text with the File's own
`source_ref`. A Code Mode script can page through every row and total it
without a provider sandbox.

### Known limits

- Word list levels come only from numbering set on the paragraph itself.
  Numbering a paragraph inherits from its style isn't resolved. Edits set list
  formatting through list styles, such as `List Bullet`.
- Word theme colours come back as `theme:<name>` without tint or shade.
- Groups nested more than five deep report `children_omitted` instead of
  their shapes.

### Embedded images

Read results list images as package part names, such as
`ppt/media/image1.png`. Word reads list images in paragraphs, tables, content
controls, headers, and footers. Deck reads list images in any shape fill and
in slide backgrounds. `view_document_image` accepts only PNG, JPEG, GIF, and
WebP parts under the format's media folder, up to 20 MiB.

### External links

Hyperlinks, linked images, and other external relationships are listed with
their kind and target, framed as File text, up to 50 per read. The worker
never fetches them.

## Edit and create tools

The edit and create tools are registered beside the read tools. They're
auto-mounted, deferred, `internal` writes with `auto` policy and no egress, and
Code Mode scripts can call them. The tools are as follows:

| Tool | Does |
| --- | --- |
| `edit_presentation(file_id, base_revision_id, operations)` | Applies deck operations and appends a File revision |
| `edit_workbook(file_id, base_revision_id, operations)` | Applies workbook operations and appends a File revision |
| `edit_word_document(file_id, base_revision_id, operations)` | Applies Word operations and appends a File revision |
| `create_presentation(name, operations, template_file_id?, keep_template_content?, folder?)` | Builds a deck from a template File or the default, then applies operations |
| `create_workbook(name, operations, template_file_id?, folder?)` | Builds a workbook from a template File or the default, then applies operations |
| `create_word_document(name, operations, template_file_id?, keep_template_content?, folder?)` | Builds a document from a template File or the default, then applies operations |

Operations are Pydantic discriminated unions in
`services/documents/operations/`, one module per format, capped at
`DOCUMENT_TOOLS_MAX_OPERATIONS`. The worker applies them in
`services/documents/{pptx,xlsx,docx}_edit.py`.

### Edit contract

Each edit follows these rules:

- `base_revision_id` must be the File's current revision. The tool checks it
  before loading the file, and `append_file_revision` checks it again against
  the File row it locks and reloads when it saves. A stale base, including a
  revision another session saved while the worker ran, fails with the current
  revision id and saves nothing.
- Operations run in order against the file in memory, so each one sees the
  document as the earlier ones left it. The first operation that doesn't fit
  fails the call with its index, such as `operations[3] (set_cells)`, and
  nothing is saved. Unexpected library errors report only their type, because
  library messages can quote file content.
- Error messages and change summaries never quote file text. File-supplied
  names that operations target, such as sheet, table, layout, and style names,
  appear capped at 100 characters, as reads show them. A Word paragraph whose
  text doesn't start with `expect_text` is refused without showing what it
  does say.
- The result has `warnings`, `changes` (one entry per operation, with ids such
  as a new `slide_id`), `readback`, and the new `revision_id` and
  `revision_number`. The read-back uses the read tools' shapes: touched slides
  for decks; touched body blocks, content controls, headers, footers, and new
  comments for Word; and every written cell for workbooks, with `value: null`
  for a cleared cell. Its text is framed as File text from the base revision.
- The whole result fits one read page (`DOCUMENT_TOOLS_READ_MAX_CHARS`).
  Warnings come first, then changes, which together take at most half the
  page, then the read-back. What doesn't fit is counted in `warnings_omitted`
  or `changes_omitted`, or flagged as `slides_truncated`, `blocks_truncated`,
  `headers_truncated`, and so on; read the new revision for the rest. The
  edit is saved either way.
- Platform Files are read-only; edit a workspace copy.
- Each saved edit records one File `update` audit event with the tool, base
  and new revision ids, operation count, and source and output byte counts.
  Creates record a File `create` event with the template File and revision
  when one was used. Both name the agent and the person who asked.
- The worker re-applies the pre-check to its own output before returning it.

Image Files for `add_image` and `replace_image` must be PNG or JPEG Files the
conversation can see, up to 20 MiB each. Published platform Files count, as
they do for other File inputs; only the File being edited must be a workspace
File. The host loads them through
the same gate as other File inputs (`services/documents/inputs.py`) and sends
them to the worker packed after the document bytes, so one call stays inside
`DOCUMENT_TOOLS_MAX_SOURCE_BYTES`.

A Code Mode script that has read document text is tainted, so its edit and
create calls wait for approval, as any tainted write does. See
[untrusted data in Code Mode](../architecture/code-mode.md#untrusted-data-whole-interpreter-taint).

### Operations

Decks target slides by `slide_id` and shapes by `shape_id`. `set_text`,
`add_slide` placeholders, and table cells keep the first existing paragraph's
and run's formatting for new text, without its link, unless a run sets its
own. `replace_text` keeps run formatting; a match that spans runs takes the
first run's formatting. `set_text` warns when a shape's text grows by half
and at least 40 characters. `duplicate_slide` shares images and external
links with the copy and refuses slides with charts, media, or embedded
objects. The copy keeps the slide's transition, animation timing, colour
map, hidden state, and notes with their formatting. `set_table` refuses a row
count change that would cut through a vertically merged cell or copy a last
row that is part of one. `replace_image` removes any crop and warns when the new image's shape
differs from its frame. Charts are native category charts; `set_chart_data`
refuses scatter and bubble charts.

Workbooks target sheets by name and cells in A1 notation. A string starting
with `=` is a formula. After all operations, every formula the call wrote,
every name it defined, and every conditional format rule and chart it added is
tokenised with openpyxl's tokenizer and checked as it stands at the end, from
the sheet it lives on. A reference to a missing sheet, defined name, or table,
or to `#REF!`, fails the call. A sheet-local name counts only on its own sheet
or with that sheet as prefix, such as `Sales!Target`. Names inside `LET` and
`LAMBDA` formulas aren't checked.

The tokenizer isn't a full Excel grammar check. It accepts some malformed
formulas, such as `=SUM(A1`, and refuses spill references such as `=A1#`,
which fail the call. It doesn't evaluate formulas.

`rename_sheet` rewrites references to the sheet in every formula cell,
defined name, conditional format, data validation, and chart the call added.
`delete_sheet` fails when any of those still refers to the sheet; names local
to the deleted sheet go with it. `merge_cells` fails when a cell other than the
top-left one has a value, comment, or link, because merging would clear it.
`append_rows` writes after the last row with a value and extends a table that
ends on that row. It refuses a table that ends with a totals row, because the
new rows would land below the totals. A write to a table's header row fails
unless every header stays distinct text; a saved table's headers can't change,
because Excel names its columns and structured references after them. A
case-only `rename_sheet`, such as `Sales` to `sales`, keeps the exact name.
Dropdowns from `add_data_validation` reject typed values outside the list.
Frozen-pane cells and chart anchors must lie inside the sheet. Saved
workbooks set full recalculation on open, adding calculation properties when
the file has none.

Word operations target body paragraphs by index plus `expect_text`, and body
tables by index, numbered as `read_word_document` numbers them. Operations
that would remove images, fields, links, comment anchors, or section breaks
fail instead: `set_paragraph` and table cell writes refuse such content, and
`replace_text` changes only plain runs, including runs inside links; runs
with nonbreaking or soft hyphens are left as they are. `set_table_cells`
writes a merged cell at its first position and refuses text for the positions
it covers. Rows it adds copy the last row's row, cell, paragraph, and run
formatting but none of its content, bookmarks, or comments, and a vertical
merge in that row ends there. Text rewrites put new runs where the old ones
were, so a bookmark around the whole paragraph keeps covering it; one around
only part of it fails the operation, as does a bookmark in a cell paragraph
that a cell write would remove. `delete_paragraphs` fails when a bookmark or
comment range reaches outside the deleted paragraphs, and removes comments
whose whole range it deletes. Images fit the page width of the section they
land in. `set_header` and `set_footer` replace text paragraphs and keep
paragraphs with images or fields, such as page numbers, and warn that they
did. A section that showed an earlier section's header or footer gets its own
copy of it first, so its images and fields stay and the earlier section is
unchanged. Even-page
headers need the document's even-page setting. Comments use the agent's name
as the author. When the body would end with a table, an empty paragraph
follows it.

### Templates

`create_presentation` and `create_word_document` start from
`template_file_id` when given. Without `keep_template_content`, the deck's
slides are removed so only its layouts remain, and the document's body and
comments are removed so its styles, sections, headers, and footers remain.
Each section break stays as an empty paragraph, which counts in paragraph
indexes. Content added without an index goes into the last section.
`create_workbook` keeps a template's sheets and cells.

Without a template, the tools use the bundled defaults in
`services/documents/templates/`:

- `default.pptx` is python-pptx's neutral default deck widened to 16:9, with
  title, title and content, section header, two content, comparison, title
  only, blank, and caption layouts.
- `default.docx` is python-docx's default document, with heading, list, and
  table styles.
- `default.xlsx` is a blank workbook with one sheet, `Sheet1`.

### Workbook edit limits

An edit needs a full openpyxl load, so the worker checks a workbook before
loading it:

- It counts cell elements by streaming each sheet part through an
  entity-refusing XML parser, so the count holds in any encoding the part
  declares, and refuses a workbook with more than
  `DOCUMENT_TOOLS_EDIT_MAX_CELLS` cells. Counting stops once the total passes
  the limit; at the limit it takes about 2 seconds. The default of
  1,500,000 stays under the 1.8 million numeric cells measured to load and save
  within the 1 GiB worker limit. The memory limit stays in force for workbooks
  whose strings or styles cost more.
- It refuses workbooks with parts openpyxl drops when it saves, by checking
  every part against the ones it keeps: sheets, styles, shared strings,
  themes, tables, legacy comments, pivot tables, external links, and document
  properties. Calculation chains, printer settings, and thumbnails can go.
  Anything else refuses the edit, including charts, drawings (images and
  shapes), chart sheets, threaded comments, slicers, timelines, data models,
  queries and connections, form controls, embedded objects, pictures in cells,
  dynamic array metadata, and custom XML data such as SharePoint properties.
  The message names the features and the sheets with drawings.
- It refuses workbooks whose load warns that an extension will be removed,
  such as extended data validation, conditional formatting, or sparklines.

`add_chart` in a workbook therefore works only in the last edit. openpyxl
doesn't compute formulas and doesn't keep the values Excel saved, so after any
edit every formula reads back with `calculated: false` until the workbook is
opened in Excel. The result warns about this whenever the workbook has
formulas.

## Agent guidance

Guidance lives in two places. Each tool description carries the short rules
and the known limits that apply to that tool: read before editing, pass the
read's `revision_id`, keep the file's formatting, write formulas for derived
values, and compare the read-back with what was meant. The internal skill
`runtime/internal_skills/office-documents.md` holds the longer working rules:
which tool to use, editing someone's file rather than recreating it, checking
every reported number in a `run_code` script, the approval each tainted
write needs, and reporting the change in outcome language.

Saved-result previews, report tool descriptions, attachment text, and
`read_file` failures point at `read_table` and the Office read tools. The
`run_code` description names the document tools as the way a script works
with files.

The `document_*` cases in `evals/datasets/agent_behavior.yaml` check the first
call a model makes after a read: creating a deck from a template, adding
formula totals to a workbook, editing a Word paragraph and commenting on it,
and totalling a saved report with `read_table` in `run_code`. Their
fixtures in `tests/fixtures/document_evals/` are real read and preview
results. The `AcceptedToolCall` evaluator validates the call's arguments
against the tool's schema, directly or inside `run_code`.

## Conversation rows

Every document tool renders one row family,
`apps/web/src/features/conversations/components/document-tool-row.tsx`, with
parsers in `native-tools/document-tools.ts`. Completed calls render as result
cards with the File, a Details popover, and an outcome badge, as the other
file tools do, including inside `run_code` scripts. A result shape the
parsers don't recognise, such as a bounded preview of an oversized read,
falls back to the generic row.

- Reads show the File, the part read (such as "Slides 1–5 of 12" or
  "Sales, A1:F200"), whether more remains, and slide titles, sheet names, or
  headings. `read_table` adds a five-row preview.
- `view_document_image` shows the File and the image reference. The stream
  drops image bytes, so the row has no thumbnail of the embedded image.
- Edit and create approvals show the declared fields and one phrase per
  operation kind with counts, such as "Write 12 cells in Sales", never the
  raw operations.
- Completed edits link "Saved as version N" to the File's history and list
  the first five changes. Creates show the new File, its folder, and the
  template named in the call. A result with warnings opens its card and
  shows them first, and read-back values sit in collapsed details.
- A stale base shows that the File changed after the agent read it and
  nothing was saved; other refusals show the tool's message.

File text, names, and read-back values render as plain text only.

## Worker processes

`services/documents/worker.py` owns a process-local pool. The API process
and the jobs worker each start their own worker processes on the first
document call and reuse them after that, in whichever process is running
the agent turn. At most `DOCUMENT_TOOLS_WORKERS` calls run at once. A call
waits up to `DOCUMENT_TOOLS_TIMEOUT_SECONDS` for a free worker and then
fails as busy; once it has a worker, the same limit applies to processing.
Starting a new worker process takes under a second.

Each worker process:

- starts with a minimal environment (`LC_ALL` and `OPENPYXL_DEFUSEDXML`
  only), so it has no application settings, secrets, or credentials. It
  never imports `core.settings`;
- sets `RLIMIT_AS` to `DOCUMENT_TOOLS_WORKER_MEMORY_BYTES` and a per-call
  `RLIMIT_CPU` budget before any Office library loads;
- takes bytes and JSON in and returns bytes and JSON out, as
  length-prefixed frames. The parent never unpickles worker output;
- has no database session, storage client, or network need.

The pool kills a worker when a call passes `DOCUMENT_TOOLS_TIMEOUT_SECONDS`,
when the caller is cancelled, or when the worker dies. A worker that hits
its memory limit exits. The call fails with `DocumentWorkerError`, and the
next call gets a fresh worker. `close_document_worker_pool()` runs in the API
and jobs worker shutdown paths, next to the Code Mode executor. It stops
running workers and any worker still starting, and later calls fail.

macOS doesn't enforce `RLIMIT_AS`, so local development on a Mac relies on
the timeout alone. Linux, which CI and every deployment use, fails to start
a worker whose memory limit can't be set.

## Pre-check

`services/documents/precheck.py` runs inside the worker before any library
opens the file. It checks the zip directory first, then decompresses each
part in bounded chunks, stopping one byte past its declared size. It rejects:

- more than `DOCUMENT_TOOLS_MAX_ZIP_ENTRIES` parts;
- a declared uncompressed total over `DOCUMENT_TOOLS_MAX_UNCOMPRESSED_BYTES`;
- any part whose actual size or CRC differs from its declared values;
- any part of 1 MiB or more whose actual size is beyond
  `DOCUMENT_TOOLS_MAX_COMPRESSION_RATIO` times the compressed bytes it
  used. Smaller parts stay inside the total bound;
- absolute paths, `..`, backslashes, drive letters, and duplicate names
  (compared without case);
- encrypted parts and compression methods other than stored and deflate;
- `vbaProject.bin` parts and macro-enabled content types (`.pptm`, `.xlsm`,
  `.docm`). `[Content_Types].xml` is parsed with `defusedxml`, with DTDs
  forbidden, so the check holds for any XML encoding. Malformed XML fails.

Python's `zipfile.read()` inflates a whole part before trimming it to the
declared size, so declared sizes alone don't bound memory. Because the
pre-check proves actual sizes match, the libraries' own reads stay within
the bounds. Save helpers apply the same pre-check to their own output.

## XML entities

No library resolves entities or loads external resources:

- `openpyxl` parses workbook parts with `lxml` and `resolve_entities=False`,
  and streams worksheets through `defusedxml`, which refuses entity
  declarations. The worker refuses to start if `openpyxl.DEFUSEDXML` is
  false.
- `python-pptx` and `python-docx` parse with `resolve_entities=False`.
  `libxml2` rejects a billion-laughs part, and an external entity stays an
  unresolved reference with no text.

## Settings

| Setting | Default |
| --- | --- |
| `DOCUMENT_TOOLS_MAX_SOURCE_BYTES` | 50 MiB |
| `DOCUMENT_TOOLS_MAX_UNCOMPRESSED_BYTES` | 200 MiB |
| `DOCUMENT_TOOLS_MAX_ZIP_ENTRIES` | 5000 |
| `DOCUMENT_TOOLS_MAX_COMPRESSION_RATIO` | 100 |
| `DOCUMENT_TOOLS_MAX_OPERATIONS` | 500 |
| `DOCUMENT_TOOLS_EDIT_MAX_CELLS` | 1500000 |
| `DOCUMENT_TOOLS_READ_MAX_CHARS` | 60000 |
| `DOCUMENT_TOOLS_TIMEOUT_SECONDS` | 60 |
| `DOCUMENT_TOOLS_WORKER_MEMORY_BYTES` | 1 GiB |
| `DOCUMENT_TOOLS_WORKERS` | 2 |

`openpyxl` loads a whole workbook into memory at about 100 times its
compressed size. Measured on Linux, a dense 200,000-row, 10-column workbook
(9.3 MB) peaks at 890 MB of address space, near the 1 GiB limit. A full load
followed by a save, as an edit needs, handles about 1.8 million numeric cells
within 1 GiB and fails at 2.1 million. Larger workbooks fail with a memory
error rather than slowing the host. Reads stream cell rows, so numeric
workbooks read well past this size, but shared strings and styles still load
whole. Decks and documents peak under 100 MB.
