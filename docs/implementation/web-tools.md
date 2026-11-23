<!-- docs/implementation/web-tools.md -->

# Web tools

Read this before changing `fetch_url`, `check_urls`, `ask_url`, the shared web transport,
or saving fetched pages. Backend paths are relative to `apps/api/`.

The web tools split by job:

| Tool | Job | Backend | Cost | Code Mode |
| --- | --- | --- | --- | --- |
| `ask_url` | Answer a question about one page | Anthropic or Google helper model | Helper tokens | No |
| `fetch_url` | Return one URL's content | Praxis HTTP | None | Yes |
| `check_urls` | Status, redirects, and headers for many URLs | Praxis HTTP | None | Yes |
| `inspect_page` | Structured facts about a page, sitemap, or `robots.txt` | Praxis HTTP | None | Pending |

`inspect_page` is pending. `fetch_url` and `check_urls` need no model
provider, so they work on a deploy with any single provider.

## Shared transport

`services/web/fetch.py::fetch_url` is the one public-web GET. It validates
each hop with `validate_public_url`, checks the denylist with
`blocked_domain_for_host`, resolves and vets every address, and pins the
request to the first address while keeping the original `Host` header and
TLS name. It never sends cookies, credentials, or caller headers, and it
ignores environment proxies.

The transport returns a `FetchedResponse` for any status and raises
`WebFetchError` only for transport failures. Each error has an
`error_class`, such as `non_public_address`, `blocked_domain`, `timeout`, or
`too_large`. A `403`, `429`, or `503` with a `cf-mitigated` or
`x-amzn-waf-action` header sets `blocked_by_site`.

The Knowledge Base URL source adapter (`services/kb/utils.py::fetch_url`)
runs on the same transport with its own limits. For its behaviour, see
[Knowledge sources](knowledge-sources.md).

## Settings

The web tools read these settings from `core/settings/web.py`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `WEB_FETCH_BLOCKED_DOMAINS` | empty | Comma-separated domains refused with their subdomains, by every web tool. While set, `ask_url` drops Google. |
| `WEB_FETCH_TIMEOUT_SECONDS` | `20` | One deadline per call covering resolution, redirects, reading, and conversion. |
| `WEB_FETCH_MAX_REDIRECTS` | `10` | Redirects one fetch follows. |
| `WEB_FETCH_MAX_BYTES` | 5 MiB | Decoded body bytes one fetch reads, including a gunzipped body. |
| `WEB_FETCH_HOST_CONCURRENCY` | `5` | Requests one run sends to a single host at once. |
| `WEB_FETCH_RUN_URL_BUDGET` | `5000` | URLs one run fetches or checks across the HTTP web tools, including in scripts that fail. |
| `WEB_FETCH_MAX_URLS_PER_CALL` | `500` | URLs one `check_urls` call checks. |
| `WEB_FETCH_BATCH_DEADLINE_SECONDS` | `120` | One deadline per `check_urls` call, under the Code Mode script timeout. |

The run budget and per-host limiter live on `RuntimeDeps.web_fetch_budget`,
so a run resumed after an approval starts a fresh count. Each setting is
wired through `apps/api/.env.example` and the GCP deploy files.

## `fetch_url`

`tools/web/fetch_url.py` registers the tool with `default_policy=auto`,
egress `arbitrary_url`, and `code_eligible=True`. It records no AI usage
events and never falls back to a helper model.

The tool takes these arguments:

- `url`: the HTTP(S) URL, on port 80 or 443.
- `format`: `markdown` (default), `text`, or `html`.
- `part`: `main` (default, page chrome removed), `body` (the whole body with
  header, navigation, footer, links, and image addresses), `head`, or `full`.
  `head` and `full` need `format="html"`.
- `drop`: for `html`, any of `scripts`, `styles`, `svg`, `comments`, and
  `data_uris`. Omitted, it drops everything except `scripts`. An empty list
  returns the source as served. `data_uris` keeps each URI's media type.
- `user_agent`: `praxis` (default, an honest `Praxis-Agents-Fetch` string),
  `desktop_browser`, `mobile_browser`, `googlebot_desktop`, or
  `googlebot_mobile`. `robots.txt` isn't enforced.
- `save_to_files` and `add_to_knowledge_base`, described in the following
  section.
- `provider`: `http` only.

`services/web/read_page.py::read_page` turns the body into content. HTML
goes to the `web_page` handler (`services/documents/web_page.py`) in the
memory-limited document worker, which applies `part` and `drop` and reads
the title. Text, JSON, XML, feeds, JavaScript, CSS, and gunzipped bodies
return verbatim. PDF and Office files convert to Markdown through the
existing document pipeline. Images and other binary bodies return
`format="unsupported"` and no content.

A `404` or `500` returns normally with its status and body. The result also
carries the requested and final URL, every redirect hop, the content type,
title, fetch time, body size, and `blocked_by_site`. Content over
`AGENT_TOOL_RESULT_MAX_CHARS` is cut, `truncated` is true, and `note` tells
the agent to save the page and read the File in windows.

A `run_code` script gets the whole text instead, up to a quarter of
`AGENT_CODE_MODE_VALUE_MAX_BYTES`, so it can parse a long page or sitemap
without paging. The transcript keeps the cut copy as the call's public
result. `read_file` works the same way: a script can read a window that
size, and the transcript keeps a `READ_FILE_MAX_CONTENT_BYTES` window.

## Saving fetched pages

`save_to_files` saves the response body as a File through `create_copy`,
with the agent as revision actor, linked to the conversation. Only a `2xx`
HTML, text, or document body is saved; HTML saves as `text/html`, and
unrecognised text saves as `text/plain`. A body that can't be saved leaves
the fetch result intact and explains why in `note`.

`add_to_knowledge_base` creates a refreshable URL source with agent
provenance and a workspace audit event. The Knowledge Base worker fetches
and refreshes the URL itself. The handler raises `ApprovalRequired` for this
argument whatever the tool's policy is, so the call waits for approval under
`auto`, including inside a script. Both arguments need a workspace role that
can edit and a run whose side-effect policy isn't `deny`.

The **Fetch URL** row has **Save to Files** and **Add to Knowledge Base**
buttons that act without an agent turn. They're hidden on shared transcripts
and for members who can't edit:

- **Save to Files** calls `POST /api/v1/web/page-saves` with the conversation
  ID and requested URL. The route fetches the page again as the person, so
  the File can differ from what the agent read. It accepts only the person's
  own conversation in the active workspace and records a File audit event.
- **Add to Knowledge Base** calls the existing
  `POST /api/v1/kb/documents/from-url` route.

## `check_urls`

`tools/web/check_urls.py` registers `check_urls(urls, user_agent,
page_facts=False)` with `default_policy=auto`, egress `arbitrary_url`, and
`code_eligible=True`. When approval is required, the URL list is editable.

- The call checks each distinct URL once, up to
  `WEB_FETCH_MAX_URLS_PER_CALL`. It reserves the URLs it checks from the
  run budget before any request. When fewer remain than it was sent, it
  checks that many and returns the rest as `not_checked`, so a script keeps
  the work it has done. `budget_remaining` reports what's left; a call with
  none left is refused.
- Requests run concurrently, at most ten at once and within the run's
  per-host limit. Each URL gets `WEB_FETCH_TIMEOUT_SECONDS`.
- Without `page_facts`, the transport closes each response after its
  headers. With `page_facts`, it reads each `2xx` body, and the `page_facts`
  worker handler (`services/documents/web_page.py`) returns the title, meta
  description, canonical, meta robots, and H1 count of an HTML page.
- `WEB_FETCH_BATCH_DEADLINE_SECONDS` bounds the call. URLs still running when
  it passes are cancelled and return `error_class="not_checked"`, so a script
  can send them again. The run budget isn't refunded for them.

A site check is one script: fetch `robots.txt` and the sitemap index, parse
each child sitemap, and send its URLs to `check_urls` in batches. At the
defaults, a 5,000-URL site fits in the run budget, and five requests at once
to one host check a few hundred URLs a minute.

Each row has the requested URL, status, redirect hops, final URL, content
type, content length, the `x-robots-tag`, `link`, `cache-control`,
`strict-transport-security`, and `last-modified` headers, time to first
byte, `blocked_by_site`, `error_class`, and `page`. A transport failure is a
row with no status and its error class, with the hops followed before it.
The result has `checked` and `not_checked` counts. `preview_list_path` is
`rows`, so an oversized result keeps every row in the retained File
snapshot, while a nested Code Mode call gets the complete result.

The **Check URLs** row is a `DataTable` with filters for OK, Redirected,
Broken, Blocked, and Not Checked. Title and H1 columns appear when the call
read page facts.

## `ask_url`

`tools/native/ask_url.py` registers `ask_url(url, question, provider,
model)`. The provider opens the URL with its native web fetch, so the tool
is available only for direct Anthropic and Google (direct or Vertex).
Anthropic's Vertex transport doesn't support native web fetch.
`NATIVE_WEB_FETCH_MAX_STEPS` bounds helper model requests and
`NATIVE_WEB_FETCH_MAX_CONTENT_TOKENS` is passed to the provider. The
denylist is checked before dispatch and passed natively. Google is
unavailable while it's set because URL Context can't enforce domain
filtering. Usage is metered as `web_fetch`. When approval is required, the
URL and question stay editable.

## Untrusted content

Every string from the remote server crosses dispatch as a `web_fetch`
provenance node: `fetch_url` content, title, final URL, content type, and
redirect hops; `check_urls` final URLs, content types, headers, redirect
hops, and page facts; and the `ask_url` answer. The model sees them inside
the shared untrusted frame, and a `fetch_url` or `check_urls` result taints
a Code Mode interpreter. The web app shows fetched HTML as source text and links only
`http` and `https` URLs. For the threat analysis, see row (f) of the
[threat model](../architecture/threat-model.md).

## Tests

These suites cover the web tools:

- `tests/services/web/test_fetch_url.py`: address checks, pinning,
  redirects, denylist and port rules on a redirect, status as a result, the
  challenge marker, and byte and gzip limits.
- `tests/services/documents/test_web_page.py`: `part` and `drop` selection,
  and page facts.
- `tests/scenarios/test_fetch_url.py`: a page read with every helper set to
  fail and no `web_fetch` usage, a hostile title framed only in the model
  request, the run budget, the saved File's workspace,
  `add_to_knowledge_base` approval and denial, and a script reading a page
  and its saved File whole while the transcript keeps the cut.
- `tests/scenarios/test_check_urls.py`: a script checking 100 URLs in one
  nested call and returning the broken ones with their hops, the tainted
  script, a batch larger than the run budget returning its checked rows,
  and `not_checked` rows past a shortened deadline.
- `tests/scenarios/test_ask_url.py`: approval editing of the URL and
  question, and the denylist retry.
- `tests/routes/web/test_save_fetched_page.py`: the person's save and the
  refusal of another member's conversation.
