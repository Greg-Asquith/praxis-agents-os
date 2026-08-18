# Technical language guide

How agents working in and on Praxis Agents OS should write. It covers three
contexts:

1. [Communicating with users](#communicating-with-users)
2. [Writing public documentation](#writing-public-documentation)
3. [Writing comments and docstrings in code](#writing-comments-and-docstrings-in-code)

The guide is adapted from the
[Google developer documentation style guide](https://developers.google.com/style).
When this guide is silent, follow that guide; when the two conflict, this
guide wins. Consistency within a document beats strict rule compliance —
depart from a rule only when doing so clearly improves the text.

## Core principles

These apply in every context: chat replies, docs, README files, error
messages, commit messages, comments, and docstrings.

### Voice

- **Address the reader as "you".** Don't write "the user" when you mean the
  reader, and don't use "we" unless it unambiguously means the Praxis team.
- **Use active voice.** Make clear who or what performs each action: the
  reader, the agent, the server, or the platform.
  - Recommended: "Send a query to the service. The server sends an
    acknowledgment."
  - Not recommended: "The service is queried, and an acknowledgment is sent."
  - Passive voice is acceptable when the actor is irrelevant or when naming
    the actor would assign blame ("Over 50 conflicts were found in the file").
- **Use present tense.** Reserve "will" for actions that genuinely happen
  later, such as asynchronous work: "The file will be archived the next time
  the backup process runs." Never use "will" for ordinary behavior ("The
  server will send an acknowledgment") or hypothetical "would".
- **Be conversational, friendly, and respectful** — like a knowledgeable
  colleague, not a legal notice and not a hype reel. Contractions ("don't",
  "isn't") are encouraged, especially for negation, because a reader can skim
  past "not" but rarely misreads "don't".
- **Don't anthropomorphize software.** Systems don't "see", "think", "want",
  or "believe". Write what actually happens: "The API detects a new device",
  not "The API sees a new device".

### Sentences and structure

- **Put the condition, goal, or context before the instruction**, so readers
  can skip what doesn't apply to them.
  - Recommended: "To delete the entire document, click **Delete**."
  - Not recommended: "Click **Delete** if you want to delete the entire
    document."
- **State the location before the action**: "In the workspace settings, click
  **Members**", not "Click **Members** in the workspace settings."
- **Keep sentences short** — under roughly 26 words. One idea per paragraph,
  most important information first. Readers scan; don't bury the point at the
  end.
- **Avoid double negatives and exceptions to exceptions.** "You can continue
  without a path" beats "A missing path won't prevent you from continuing."
- **Prefer positive constructions** — say what the reader can do, not what
  they can't.

### Words

- **No "please" in instructions.** "To view the document, click **View**",
  not "please click **View**".
- **Never "simply", "easily", "just", "obviously", or "It's that simple".**
  If it were simple, the reader wouldn't be reading instructions. Delete the
  word or replace it with something specific.
- **Plain words over fancy ones**: "use" not "utilize" or "leverage",
  "about" not "approximately", "go to" not "navigate to", "so" not
  "consequently", "start" not "commence".
- **No Latin abbreviations**: write "for example" not "e.g.", "that is" not
  "i.e.". No internet slang ("tl;dr", "ymmv").
- **No idioms, metaphors, pop-culture references, or humor that depends on
  culture.** The audience is global and text may be translated. "Ballpark
  figure", "back burner", and "pets versus cattle" don't travel.
- **Avoid jargon.** Write around it, or define it in plain language on first
  use: "You then move the task to an earlier part of the process (also known
  as *shifting left*)."
- **Inclusive language**: singular "they", never assumed gender; "allowlist"
  and "denylist", not "whitelist" and "blacklist"; "primary/replica", not
  "master/slave"; "placeholder", not "dummy"; "final check", not
  "sanity check"; "doesn't respond", not "hangs". When code uses a
  non-inclusive keyword, name it once in code font and use the inclusive term
  in prose afterward.
- **Spell out abbreviations on first use** with the short form in
  parentheses — "recovery point objective (RPO)" — except universally known
  ones (API, AI, URL, HTML, JSON, CPU, RAM).

### Claims and time

- **Write timelessly.** Avoid "currently", "now", "new", "soon", "as of this
  writing", "does not yet". Docs describe the product's current state; the
  document's existence already implies the present tense. This repo's rule is
  stricter: if a capability is not wired end to end, document it as pending
  rather than implying it works — and never document unreleased features.
- **No excessive claims.** Avoid superlatives and absolutes ("best",
  "fastest", "never fails"). Use "ensures" or "guarantees" only when
  literally true; otherwise write "helps" or "is designed to". Frame security
  claims as part of a strategy ("helps prevent account takeovers"), never as
  a guarantee. Don't disparage or make unsupported comparisons to other
  products.
- **Be prescriptive.** Recommend one way to do a task — the simplest — rather
  than cataloguing every option. Requirement words carry exact meaning:
  - **must** — required.
  - **we recommend** — suggested; use "should" only for widely recognized
    best practice.
  - **can** — optional.
  - State expected outcomes as fact ("The process returns 10 items"), use
    "might" or "can" for possible outcomes, and never use "should" for a
    state ("The value should be true" — write "Set the value to `true`").

## Communicating with users

This section governs agent-to-user text: chat replies, run summaries,
notifications, approval prompts, and error explanations.

### Know the audience

The Praxis operator is a non-technical user. Complexity belongs behind good
defaults, not in their face:

- **Use outcome language, not mechanism language.** "I've scheduled the
  report to send every Monday at 9 AM", not "I created a cron entry with
  expression `0 9 * * 1`."
- **Don't surface internal identifiers, stack traces, table names, or HTTP
  status codes** unless the user asks or needs them to act. Translate:
  "I couldn't reach Google Calendar — the connection needs to be
  reauthorized", not "Received `401 Unauthorized` from the OAuth token
  endpoint."
- **Define any unavoidable technical term in the sentence that uses it.**

### Lead with the outcome

The first sentence of a reply answers "what happened" or "what did you find".
Detail and reasoning come after, for readers who want them. Don't make the
user excavate the answer from a narrative of what you tried.

### Report faithfully

- State results plainly: what succeeded, what failed, what you skipped.
  Never imply something worked when it didn't or is unverified.
- If an action failed, say what failed and what fixes it: "The upload failed
  because the file is larger than 50 MB. Split it or compress it, then try
  again." Error text without a next step is a dead end.
- Distinguish fact from possibility: "The export completed" versus "The
  export can take about 30 minutes."
- For actions that affect external systems or are hard to reverse, say what
  you are about to do — in concrete terms — before doing it, and confirm when
  the platform's approval flow requires it.

### Instructions in conversation

- Condition first, then instruction (see [Core principles](#core-principles)).
- For a sequence of steps, use a numbered list — one action per step, in the
  order the user performs them. For a single step, use a plain sentence.
- Bold UI element names exactly as they appear on screen: "Click **Create
  agent**." Refer to elements by label, never by appearance or position —
  "click **Save**", not "click the blue button on the right". Directional
  language ("above", "below", "left-hand side") breaks on small screens and
  for screen readers; use "earlier", "following", or the element's name.
- Recommend one way to do the task, not an inventory of alternatives.
- Interaction verbs: **click** (mouse), **tap** (touch), **press** (keys),
  **enter** (text into a field), **select** and **clear** (checkboxes),
  **turn on** and **turn off** (toggles).

### Tone calibration

Aim for the middle column:

| Too informal | Just right | Too formal |
|---|---|---|
| "Boom — your agent is live!" | "Your agent is running. It checks for new invoices every hour." | "The agent instantiation procedure has completed successfully." |
| "Oops, that totally broke." | "That didn't work — the spreadsheet is missing a **Date** column." | "An error condition was encountered during processing." |

No exclamation marks except rarely, no wackiness, but no bureaucratic stiffness
either. Vary sentence openings — don't start every sentence with "You can" or
"To do".

## Writing public documentation

This section governs README files, `docs/`, architecture notes, release
notes, and any prose published with the project.

### Titles and headings

- **Sentence case** for every title and heading: "Create an agent", not
  "Create An Agent". No end punctuation.
- Task-based headings use the bare infinitive: "Create an instance", not
  "Creating an instance". Conceptual headings use a noun phrase: "Migration
  to Google Cloud", not "Migrating to Google Cloud". Avoid starting a heading
  with an "-ing" word.
- Don't skip heading levels, don't put links or code alone in headings, and
  give every heading real content beneath it. Prefix optional sections with
  "Optional:".
- Include articles ("a", "an", "the") even in headings: "Create a VM
  instance", not "Create VM instance".

### Paragraphs, lists, and tables

- One idea per paragraph, key point first, five to six sentences at most.
  Left-align everything; never center or justify.
- **Numbered lists** for sequences, **bulleted lists** for everything else,
  **description lists** for term-definition pairs. Never a one-item list.
- Introduce every list, table, and code block with a complete sentence ending
  in a colon (or a period if other material intervenes): "The fields are
  defined as follows:", not the fragment "The fields are:".
- Keep list items grammatically parallel. End an item with a period if it's a
  sentence; omit it for single words, fragments without verbs, or pure code.
- Use a table when each item carries three or more pieces of related data.
  Sentence case for headers and cells; never merge cells; sort rows logically
  or alphabetically.
- Use notes, cautions, and warnings sparingly — a page full of callouts has
  none. Never stack two callouts. **Note** is skippable context, **Caution**
  means proceed carefully, **Warning** means an irreversible or destructive
  outcome.

### Links

- Link text is the target's title or a descriptive phrase — never "here",
  "this page", or a raw URL. Important words first.
- Standard form: "For more information, see [Configure schedules]." Use
  "see" for cross-references and "about" rather than "on" ("information about
  schedules").
- Punctuation stays outside the link text. Include an abbreviation inside the
  link text: "[Google Kubernetes Engine (GKE)]".
- Link each destination once per page, at the most useful spot. Say when a
  link downloads a file or leaves the project's domain.

### Procedures

- One action per numbered step, imperative mood, in order.
- Location, then action: "In the workspace settings, click **Members**."
- Goal, then action: "To start a new document, click **File > New >
  Document**."
- Put a step's result in the same paragraph as the action, after it.
- Menu paths use `>` with bold: "Click **File > New > Document**."
- Mark optional steps with a leading "Optional:".
- Say what a command does — never just "run the following command".
- Document the single recommended path; put alternatives under separate
  headings if they must exist.

### Code in documentation

- **Code font** (backticks) for: filenames and paths, class, method, and
  function names, command names, flags, environment variables, HTTP verbs
  and status codes (`400 Bad Request`), keywords, enum values, port numbers,
  query parameters, text the user types, and placeholders.
- **Bold** for UI element names. An element that is both UI and code gets
  both: **`main.py`**.
- No code font for product names, conceptual references, or URLs the reader
  visits in a browser.
- **Placeholders** are `UPPER_SNAKE_CASE` in code font — `PROJECT_ID`, never
  `my-project-id`, `xxx`, or `YOUR_PROJECT`. After the sample, explain each
  one: "Replace `PROJECT_ID` with the ID of your project." For several, lead
  with "Replace the following:" and list them in order of appearance.
- Introduce every sample with a sentence ending in a colon. Wrap lines at 80
  characters. Indicate omitted code with a language-appropriate comment
  ("# Lines omitted"), never bare `...` inside a copyable block.
- Show output only when it helps, introduced with "The output is similar to
  the following:".
- Command syntax: square brackets for optional arguments, `{A|B}` for
  mutually exclusive ones, `...` for repeatable ones — and never any of those
  inside a click-to-copy block.

### Example values

Never use real data or personally identifiable information:

- Domains: `example.com`, `example.org`, `example.net`.
- Email addresses: `dana@example.com` — name from the diverse, gender-neutral
  set (Alex, Amal, Ariel, Charlie, Dana, Kai, Kim, Lee, Noam, Quinn, Sasha,
  Taylor, and similar), singular "they" throughout.
- Phone numbers: 800-555-0100 through 800-555-0199 only.
- IPv4: the RFC 5737 ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
  IPv6: 2001:db8::/32.
- Company: "Example Organization". Avoid `foo`/`bar`/`baz` — use descriptive
  names.

### Dates, numbers, and units

- Dates are unambiguous: "January 19, 2017", or ISO 8601 (`2017-04-15`) where
  a numeric form is needed. Never "02/12/2017". No seasons ("fall 2026") —
  hemispheres differ; use months or quarters.
- Spell out zero through nine in prose; numerals for 10 and up, and always
  for versions, step numbers, measurements, and technical quantities. Spell
  out a number that starts a sentence. Spell out ordinals ("first", not
  "1st").
- Thousands separators for numbers of four or more digits ("1,532,784").
- Nonbreaking space between a number and its unit ("64 GB"); no space for
  `%`, `°`, and currency. Repeat units in ranges ("-40 °C to 85 °C"). Use
  "per" instead of a slash where space allows ("requests per day"). Decimal
  units (kB, MB, GB) are powers of 1000; binary units (KiB, MiB, GiB) are
  powers of 1024 — use the right one.

### Images and accessibility

- Prefer text. Never use an image of text, code, or terminal output.
- Every image gets alt text (155 characters or fewer, no "Image of…");
  decorative images get empty alt text. Anything an image conveys must also
  appear in text.
- Screenshot only the relevant UI; no PII in screenshots — cover it with a
  solid overlay, never a blur.
- Refer to figures by number ("as shown in figure 1"), never by position
  ("the image above").
- Write link text and headings that make sense out of context; keep color
  from being the only carrier of meaning; don't rely on directional language.

### Punctuation quick rules

- Serial (Oxford) comma always: "zones, regions, and multi-regions".
- Em dashes with no surrounding spaces—like this. No en dashes in prose;
  hyphens for number ranges ("5-10 minutes").
- Avoid semicolons where a period works; avoid parentheses for anything
  important — some readers skip them.
- Straight quotation marks, not curly. Commas and periods inside quotation
  marks, except next to literal strings or code, where punctuation moves
  outside — better yet, use code font instead of quotes.
- Hyphenate compound modifiers before a noun ("well-designed app") but not
  after a verb ("the app is well designed"), and never after an "-ly" adverb.
- One space between sentences. No "&" as a conjunction in prose.

## Writing comments and docstrings in code

This section governs comments, docstrings, and API reference text across
`apps/api` and `apps/web`.

### Comments

- **Comment the why and the constraint, not the what.** A comment earns its
  place by stating something the code cannot show: an invariant, an ordering
  requirement, a security boundary, a non-obvious reason. Never narrate the
  next line, cite the ticket that prompted it, or address the reviewer.
- **Keep comments terse — single-line where possible.** Match the density and
  idiom of the surrounding file; this codebase favors sparse, short comments
  over block prose.
- Comments describe runtime behavior and durable design decisions, not
  planning artifacts, private scratch notes, or the history of the change.
- Use complete thoughts in plain English, present tense, active voice. The
  core word rules apply: no "simply", no idioms, inclusive terminology.
- Don't add a comment that restates a removed one, and don't reintroduce
  comments a human deliberately deleted.

### Docstrings

Document what callers need: purpose, parameters, return value, raised
exceptions, and side effects that matter (writes, network calls, locks).

**First sentence.** A docstring's first sentence states what the code does,
in third-person present tense ("the -s form"), without repeating the name and
without "This function…":

```python
def revoke_session(session_id: UUID) -> None:
    """Revokes the session and expires its refresh tokens."""
```

Not: `"""Revoke a session."""` (imperative — that describes what the caller
does, not what the function does) and not `"""This function will revoke…"""`.
Many tools extract only the first sentence, so make it self-contained, and
write "for example", never "e.g." (the period can truncate the extraction).

**Standard opening verbs**:

| Kind of function | Start with |
|---|---|
| Performs an operation | An action verb: "Adds…", "Validates…", "Publishes…" |
| Returns data | "Returns the…" |
| Boolean getter/predicate | "Checks whether…" |
| Non-boolean getter | "Gets the…" |
| Setter | "Sets the…" |
| Update | "Updates the…" |
| Delete | "Deletes the…" |
| Registers a callback | "Registers…" |
| Callback / handler (`on_*`) | "Called by… / Called when…" |
| Constructor / factory | "Creates a…" |

**Parameters.** Start with a capital, end with a period. Non-boolean
parameters begin "The…" or "A…". Boolean parameters describe both branches:
"If true, validates the certificate before proceeding. If false, trusts it
without validating." Note defaults as "Default: `value`."

**Return values.** Brief. Non-boolean: "The workspace matching the given
ID." Boolean: "True if the user is a member; false otherwise."

**Exceptions.** "Thrown when…" (or, under a generator that prints "Raises"/
"Throws", begin with the condition: "If no key is assigned.").

**Deprecations.** The first sentence names the replacement, since summaries
may show nothing else: "Deprecated. Use `create_agent_v2` instead." Then
explain why and how to migrate.

**Classes and modules.** First sentence states the purpose without repeating
the name; follow with how to use it, key invariants, and pitfalls. Constants
and fields get one brief line each.

### Referring to code in prose

- Code identifiers in code font, spelled exactly as declared (`ActionBar`,
  never "Action Bar").
- Never inflect an identifier: no plurals ("`Intent` objects", not
  "`Intents`"), no possessives ("the return value of `word_count`", not
  "`word_count`'s return value"), never as a verb ("Send a `POST` request",
  not "`POST` the data").
- Pair a filename with a noun: "the `build.sh` file". Name file types
  formally: "a PNG file", not "a `.png` file".
- Reference-doc method summaries use the third person ("Creates a new task"),
  exactly like docstring first sentences.

## Condensed word list

| Avoid | Use |
|---|---|
| e.g., i.e., aka | for example, that is, also known as |
| please (in instructions) | (omit) |
| simply, easily, just | (omit, or be specific) |
| utilize, leverage | use |
| enables/allows you to | lets you |
| navigate to | go to |
| click on | click |
| log in (as a verb) | sign in ("login" is a noun or adjective only) |
| e-mail | email |
| currently, now, new, soon | (omit — write timelessly) |
| and/or | "or", "X, Y, or both", or restructure |
| approximately | about |
| as (meaning because) | because |
| if (for alternatives) | whether |
| he/she, (s)he | they |
| blacklist / whitelist | denylist / allowlist |
| master / slave | primary / replica |
| sanity check | final check, validation |
| hangs, is hung | doesn't respond |
| grayed out, disabled | unavailable |
| dialog box | dialog |
| check/uncheck (a checkbox) | select / clear |
| hover | hold the pointer over |
| type (into a field) | enter ("type" only when literal keystrokes matter) |
| newer / older (versions) | later / earlier |
| should (for requirements) | must (required), we recommend, or can (optional) |
| 10x faster | 10 times faster |
| data are | data is |

## Precedence

1. App-specific standards in `apps/api/AGENTS.md` and `apps/web/AGENTS.md`,
   and the root `AGENTS.md`.
2. This guide.
3. The [Google developer documentation style guide](https://developers.google.com/style).
4. Consistency with the surrounding document or file.

---

Portions of this guide are adapted from the
[Google developer documentation style guide](https://developers.google.com/style),
used under the
[Creative Commons Attribution 4.0 License](https://creativecommons.org/licenses/by/4.0/).
