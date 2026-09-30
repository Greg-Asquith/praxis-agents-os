# Document tools

Document tools read, edit, and create `.pptx`, `.xlsx`, and `.docx` Files with
`python-pptx`, `openpyxl`, and `python-docx`. Office files are
attacker-controlled input, so every library call runs in a bounded worker
process, never in the API or worker process itself.

Status: the hardened worker runtime is implemented. The read, edit, and
create tools are pending (plan 247 slices A2 and A3).

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
(9.3 MB) peaks at 890 MB of address space, near the 1 GiB limit. Larger
workbooks fail with a memory error rather than slowing the host. Decks and
documents peak under 100 MB.
