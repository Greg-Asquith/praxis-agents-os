# Document tools

Document tools read, edit, and create `.pptx`, `.xlsx`, and `.docx` Files with
`python-pptx`, `openpyxl`, and `python-docx`. Office files are
attacker-controlled input, so every library call runs in a bounded worker
process, never in the API or worker process itself.

Status: the hardened worker runtime and the read tools are implemented. The
edit and create tools are pending (plan 247 slice A3), and so are the web
presenters for document tools (slice C1).

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
  Numbering a paragraph inherits from its style isn't resolved yet. Plan 247
  slice A3 revisits this for edits.
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
