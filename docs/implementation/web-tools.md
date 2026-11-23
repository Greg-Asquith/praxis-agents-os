<!-- docs/implementation/web-tools.md -->

# Web tools

Read this before changing `fetch_url`, `check_urls`, `inspect_page`,
`measure_page_speed`, `ask_url`, the shared web transport, or saving fetched pages. Backend paths are relative to `apps/api/`.

The web tools split by job:

| Tool | Job | Backend | Cost | Code Mode |
| --- | --- | --- | --- | --- |
| `ask_url` | Answer a question about one page | Anthropic or Google helper model | Helper tokens | No |
| `fetch_url` | Return one URL's content | Praxis HTTP | None | Yes |
| `check_urls` | Status, redirects, and headers for many URLs | Praxis HTTP | None | Yes |
| `inspect_page` | Structured facts about a page, sitemap, or `robots.txt` | Praxis HTTP | None | Yes |
| `measure_page_speed` | Speed scores and Core Web Vitals for up to 50 pages | Google PageSpeed Insights | None (the deploy's own key) | Yes |

`fetch_url`, `check_urls`, and `inspect_page` need no model provider, so
they work on a deploy with any single provider. `measure_page_speed` is
available only while `PAGESPEED_API_KEY` is set.

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
| `PAGESPEED_API_KEY` | unset | Google API key restricted to the PageSpeed Insights API. Without it, `measure_page_speed` is unavailable. Separate from `GOOGLE_API_KEY`. |
| `PAGESPEED_TIMEOUT_SECONDS` | `90` | Time for one page's test. |
| `PAGESPEED_MAX_URLS_PER_CALL` | `50` | Pages one `measure_page_speed` call tests. |
| `PAGESPEED_BATCH_DEADLINE_SECONDS` | `240` | One deadline per `measure_page_speed` call, under the Code Mode script timeout. |
| `PAGESPEED_RUN_BUDGET` | `200` | Tests one run starts, including in scripts that fail. |

The run budget and per-host limiter live on `RuntimeDeps.web_fetch_budget`,
and the test budget on `RuntimeDeps.page_speed_budget`, so a run resumed
after an approval starts a fresh count. Each setting is
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

## `inspect_page`

`tools/web/inspect_page.py` registers `inspect_page(url, include,
user_agent)` with `default_policy=auto`, egress `arbitrary_url`, and
`code_eligible=True`. When approval is required, the URL is editable. Each
call takes one URL from the run budget, plus one per script bundle scanned
for tags, and reads only a `2xx` body, gunzipping a `.gz` file. Any other status returns with `kind` null and nothing
inspected.

The response decides `kind`:

- `page`: an HTML body. `include` selects any of `meta`, `headings`, `links`,
  `images`, `structured_data`, `tags`, and `headers`; the default is `meta`,
  `headings`, and `tags`. Every page also returns `word_count` and
  `looks_client_rendered`, which is true when an app mount element such as
  `#root` is empty or the page has little text and several scripts.
- `robots`: a text body at a `/robots.txt` path. It returns groups (user
  agents, `allow`, `disallow`, crawl delay), with consecutive `User-agent`
  lines in one group, and the `Sitemap` lines.
- `sitemap`: an XML or gunzipped text body whose root is `urlset` or
  `sitemapindex`. It returns `entries` with `loc` and `lastmod`, and the
  `total`. The first 10,000 entries are returned, and `note` says when there
  are more.
- `unsupported`: any other body.

The worker handlers live in `services/documents/web_inspect.py`:
`inspect_web_page`, `read_sitemap`, and `read_robots`. Page facts cover:

- `meta`: title, description, meta robots, canonical, `html` language,
  viewport, meta refresh, `hreflang` alternates, and Open Graph properties.
  The canonical and `hreflang` URLs resolve against the page or its `<base>`.
- `headings`: the total, the H1 count, and up to 300 headings with level
  and text.
- `links`: totals for internal (same host, ignoring `www.`), external, and
  `nofollow` links, and up to 1,000 absolute `http` and `https` links.
  Fragment-only links and other schemes are left out.
- `images`: the total, the count with no `alt` attribute, and up to 500
  images. An empty `alt` marks a decorative image, and a `data:` URI keeps
  only its media type.
- `structured_data`: up to ten JSON-LD blocks, each with its `@type` values
  (including those in `@graph`), whether it parses, and its first 5,000
  characters.
- `tags`: matches from the pattern registry in
  `services/documents/web_tags.py`, with vendor, category, ID, and where it
  was found (`script_src`, `inline_script`, or `noscript`). It covers Google
  Tag Manager, Google Analytics 4, Universal Analytics, Google Ads, Meta
  Pixel, LinkedIn Insight, TikTok Pixel, Hotjar, Microsoft Clarity, and ten
  consent banners. A vendor found with an ID isn't listed again without one.
  Frameworks such as Next.js set analytics up inside the site's own script
  bundles, so the tool also fetches up to 20 same-site scripts (2 MiB each)
  and scans them with the `find_bundle_tags` handler (`found_in` is
  `script_bundle`). Each bundle counts against the run budget, fetches share
  the per-host limit, and one deadline bounds them; a bundle that fails is
  skipped, and `note` says how many weren't scanned. Third-party scripts
  aren't fetched. Tags that a tag manager loads still don't appear, so `note`
  names the Google Tag Manager container to fetch.
- `headers`: the allowlisted response headers.

Sitemaps parse with `defusedxml`, which refuses DTDs and entities. Every list
is capped in the worker and reports its full count. Without
`preview_list_path`, an oversized result previews each list and keeps every
item in the retained File snapshot.

The **Inspect Page** row starts with plain-language checks, problems first
(`inspect-page-checks.ts`): title and description length against what
search results show, canonical, `noindex`, language, viewport, H1 count,
missing alt text, and JSON-LD that doesn't parse. A client-rendered page gets
a **Needs a Browser** badge. Below are the meta fields and tabs with counts
for tags, links, images, a heading outline, and structured data, where each
JSON-LD block opens to its formatted source as text. Empty tabs are hidden.
A sitemap shows its entries, and `robots.txt` shows its rules with Disallow
and Allow filters.

## `measure_page_speed`

`tools/web/measure_page_speed.py` registers `measure_page_speed(urls,
strategy, categories)`, Code Mode eligible, provider `web`, with `urls`
editable as a `list` field in approvals. `strategy` is `mobile` (default) or
`desktop`; `categories` is any of `performance` (default), `accessibility`,
`best_practices`, and `seo`. Duplicates are tested once.

Google fetches the page, so the shared transport isn't used.
`services/web/page_speed.py::run_page_speed_test` first validates the URL
(HTTP or HTTPS on ports 80 and 443), checks the denylist, and resolves the
host to public addresses, so an internal host name never reaches Google.
It then sends one `GET` to the PageSpeed Insights v5 API with the key in the
`X-Goog-Api-Key` header, never in the URL. Ten tests run at once (a module
constant, well inside Google's per-minute quota), each within
`PAGESPEED_TIMEOUT_SECONDS`, and the call stops at
`PAGESPEED_BATCH_DEADLINE_SECONDS`. Pages the deadline or the run budget
doesn't reach return `error_class: "not_checked"`, as in `check_urls`. Other
error classes are the URL refusals (`invalid_url`, `unsupported_port`,
`non_public_address`, `blocked_domain`, `dns_failure`), `page_unreachable`
and `page_error` from Lighthouse, `key_rejected`, `quota_exceeded`,
`timeout`, and `service_error`. The tool records no usage events.

Google's response is 300 KB to 1 MB a page, so the tool never returns it.
`reduce_page_speed` keeps three levels of detail:

1. **A summary row per page** in model context: requested URL, `final_url`
   (a node, null when unchanged), category scores (0 to 100), lab metrics
   (`lcp_ms`, `cls`, `tbt_ms`, `fcp_ms`, `speed_index_ms`), real-visit
   `field` data for the page (LCP, INP, CLS, and TTFB at the 75th
   percentile, each rated, plus `core_web_vitals` passed or failed), the
   three failed performance audits with the largest estimated saving (audit
   ID and saving only), `report`, and `error_class`. Field data for each
   requested origin is in the result's `origins`, keyed like
   `https://example.com`, so 50 pages of one site carry it once. The result
   also has `tested`, `not_checked`, `budget_remaining`, and `report_file`.
   Fifty rows stay under 40,000 characters.
2. **A saved report File**: one internal tool-result File per call, written
   through `save_tool_result`, holding a JSON array with one page per line.
   Each page's report is ASCII JSON of at most 40,000 bytes: failed audits by
   category with title, description, display value, estimated saving, and up
   to 20 detail items (resource address, sizes, wasted time, element
   selector, and a snippet cut to 300 characters), the LCP element, up to 20
   third parties, passed audit IDs, run warnings, the Lighthouse version, and
   the test time. Screenshots, the filmstrip, the treemap, the network
   request list, and translation strings are dropped. Detail items are cut
   first, then audits, and `truncated` is set.
3. **One page in full, on request**: each row's `report` is a byte `offset`
   and `length` into `report_file`. `read_file` with those values returns the
   page's report in one window, with no second test.

An audit fails when its score is under 0.9 in a scored display mode
(`numeric`, `binary`, or `metricSavings`); metric audits and hidden audits
aren't issues. An estimated saving is the larger of `overallSavingsMs` and
the audit's LCP, FCP, TBT, or INP metric saving. Core Web Vitals pass when
LCP and CLS, and INP when Google has it, are all rated good; without LCP or
CLS data the assessment is null. Google reports page data from the origin
when the page has too few visits (`origin_fallback`); the row's `field` is
then null.

The **Measure Page Speed** row shows Pages Tested, Median Performance, and
Passing Core Web Vitals tiles, a device badge, and one table row per page,
lowest score first, with Good, Needs Improvement, Poor, and Not Tested
filters. A page's URL opens its detail in a popover: category scores, lab
and visitor metrics side by side against Google's thresholds, and the
report's Opportunities, Diagnostics, and other categories' issues, each
opening a popover with its description and affected resources. The card
loads that page's range of the report File through the Files revision APIs
only when the popover opens. A one-page call shows the detail in place of
the table. Report text renders as text only; Markdown links keep their words
and drop their addresses, and the one external link is PageSpeed Insights
for the agent's requested URL.

For the GCP key setup, see "Optional: Turn on page speed testing" in
`deploy/gcp/README.md`.

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
hops, and page facts; `inspect_page` meta text, headings, links, images,
JSON-LD, headers, sitemap locations, and `robots.txt` values; and the
`ask_url` answer. `measure_page_speed` returns only its final URL as a node:
scores, timings, ratings, and audit IDs (matched against a fixed pattern) are
plain values. Its report File holds Google's other strings, and `read_file`
returns tool-result Files as `file` nodes, so reading a report taints a
script too. `inspect_page` tag vendors are Praxis names, and tag IDs and
sitemap `lastmod` values must match fixed patterns, so they arrive as plain
strings. The model sees the nodes inside the shared untrusted frame, and a
result from any HTTP web tool taints a Code Mode interpreter. The web app shows fetched HTML as source text and links only
`http` and `https` URLs. For the threat analysis, see row (f) of the
[threat model](../architecture/threat-model.md).

## Tests

These suites cover the web tools:

- `tests/services/web/test_fetch_url.py`: address checks, pinning,
  redirects, denylist and port rules on a redirect, status as a result, the
  challenge marker, and byte and gzip limits.
- `tests/services/documents/test_web_page.py`: `part` and `drop` selection,
  and page facts.
- `tests/services/documents/test_web_inspect.py`: link, image, and JSON-LD
  extraction, the client-rendered hint, tag detection, a sitemap index, a
  refused DTD, and `robots.txt` groups.
- `tests/scenarios/test_fetch_url.py`: a page read with every helper set to
  fail and no `web_fetch` usage, a hostile title framed only in the model
  request, the run budget, the saved File's workspace,
  `add_to_knowledge_base` approval and denial, and a script reading a page
  and its saved File whole while the transcript keeps the cut.
- `tests/scenarios/test_check_urls.py`: a script checking 100 URLs in one
  nested call and returning the broken ones with their hops, the tainted
  script, a batch larger than the run budget returning its checked rows,
  and `not_checked` rows past a shortened deadline.
- `tests/scenarios/test_inspect_page.py`: a page's canonical, Tag Manager
  ID, and missing-alt count, a hostile title and header stored as nodes and
  framed only in the model request, and a gzipped sitemap's entries.
- `tests/services/web/test_page_speed.py`: the request's key header and
  parameters, the reducer on a recorded response (scores, lab and field
  metrics, Core Web Vitals, ranked issues, report items), the 40,000-byte
  report bound, private and denylisted URLs refused before any request to
  Google, and the error classes for Lighthouse, key, and quota errors.
- `tests/scenarios/test_measure_page_speed.py`: a script testing 50 pages in
  one nested call and returning the five slowest within 40,000 characters,
  `read_file` at one row's range returning that page's failed audits and a
  hostile snippet inside a node, the run budget refusing the next call, and
  `not_checked` rows past a shortened deadline.
- `tests/scenarios/test_ask_url.py`: approval editing of the URL and
  question, and the denylist retry.
- `tests/routes/web/test_save_fetched_page.py`: the person's save and the
  refusal of another member's conversation.
