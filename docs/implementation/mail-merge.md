<!-- docs/implementation/mail-merge.md -->

# Mail merge

A mail merge sends one personal email to each person on a list, from the
operator's own Gmail or Outlook mailbox, after one approval. Each email has one
recipient, and its placeholders are filled in mechanically from that person's
row. Merges are for Google Workspace and Microsoft 365 mailboxes; personal
Gmail and Outlook.com accounts keep lower caps as a safe default.

**Status:** pending. The records, template rendering, recipient checks,
sending budget, provider senders, and background sender described on this
page are implemented as backend services. No agent tool, approval card, or
route creates a merge yet, so an operator can't start one.

## Records

Two tables in `models/mail_merge.py` hold a merge. Both carry `workspace_id`
and have forced row-level security (`core_0082`):

- **`mail_merges`**: the approved template (`subject_template`,
  `body_template`, `fallbacks`), the mailbox (`connection_id`,
  `provider_key`, `sender_address`), the proposing tool call (`run_id`,
  `tool_call_id`, unique together), and `status` with `stop_reason`.
  - Counts aren't stored. They come from the recipient rows (at most 500),
    so they can't drift from them.
  - A partial unique index allows one `queued` or `sending` merge per
    connection. This paces sends from one mailbox across worker processes
    without a shared lock.
  - The connection, run, and creator keys are set to null when those rows go,
    so past sends still count against the mailbox's budget.
- **`mail_merge_recipients`**: one row per address, with `position`, the
  row's `fields`, `status`, the provider's message, draft, and thread IDs,
  and `attempted_at` and
  `sent_at`. Addresses are stored lower-cased and are unique within a merge.
  A row in any status other than `pending` or `skipped` must have an
  `attempted_at`.

The allowed status moves are in `services/mail_merge/domain.py`:

| Record | Moves |
| --- | --- |
| Merge | `queued` to `sending`, `paused`, `cancelled`, or `stopped`; `sending` to `paused`, `completed`, `cancelled`, or `stopped`; `paused` to `queued` (resume), `cancelled`, or `stopped` |
| Recipient | `pending` to `sending` or `skipped`; `sending` to `pending` (the provider rejected the send), `sent`, `failed`, or `unverified` |

`completed`, `cancelled`, `stopped`, `sent`, `failed`, `unverified`, and
`skipped` are final. A recipient whose send outcome is unknown becomes
`unverified` and is never sent again automatically: a missed email is visible
and fixable, and a duplicate is neither.

## Templates

`services/mail_merge/render.py` fills a template with no model involved:

- Placeholders are `{{column}}` or `{{column|fallback}}`. A `fallbacks`
  argument can also give a fallback per column. An inline fallback wins.
- `parse_merge_template` rejects the whole template when a placeholder is
  malformed or names a column the recipients don't have, when a fallback
  names an unknown column, or when the subject or a fallback has a line break.
  It sanitises the body once with `sanitize_preview_html`.
- `render_merge_email` fills one row. A blank value with no fallback, a
  subject value with a line break, or a subject longer than 998 characters
  returns problems instead of an email, so the row is never sent with a gap.
- Body values are HTML-escaped. The filled body is sanitised again, because a
  value placed in an attribute could otherwise form a link.
- The same template and values always give the same bytes.
  `content_fingerprint` hashes the subject, body, and fallbacks, so an edit
  after an approval's test send shows.

## Recipient checks

`check_mail_merge` (`services/mail_merge/recipients.py`) parses the template
against the rows' columns and marks each row:

| Result | When |
| --- | --- |
| Ready | The address is valid and the row renders |
| Needs Attention | The address isn't valid, or the row doesn't render |
| Skipped | The sender's own address, a case-insensitive duplicate of an earlier row, or an address the Do Not Email guard refuses |

Rows can also carry warnings for the operator: names in all capitals or all
lower case, names with an `@` or digits, and role addresses such as
`noreply@`. Warnings don't stop a send.

The check calls `find_suppressed_recipients` from the Do Not Email guard and
never reads the list directly. A skipped row's reason is for the operator's
card; a tool result reports only that the row was skipped. Gmail dots aren't
folded for duplicates, but the guard matches plus-tags and Gmail dots, as
described in [Integrations](integrations/README.md).

A merge has at most `MAIL_MERGE_MAX_RECIPIENTS` rows and 10 columns besides
`email`, `first_name`, and `last_name`. Column names use letters, digits,
and underscores, so a placeholder can name them.

## Sending budget

A mailbox never uses more than half of its provider's daily limit through
merges. Providers count their limits over a rolling 24 hours, covering every
email the mailbox sends, so the budget does the same.

`mail_account_kind` picks the cap:

| Account kind | Detected by | Setting | Default |
| --- | --- | --- | --- |
| Personal Gmail | Gmail with a `gmail.com` or `googlemail.com` address | `MAIL_MERGE_DAILY_CAP_GMAIL_PERSONAL` | 250 |
| Google Workspace | Gmail with any other domain | `MAIL_MERGE_DAILY_CAP_GOOGLE_WORKSPACE` | 1,000 |
| Outlook.com | Outlook with the Microsoft consumer tenant, or no recorded tenant | `MAIL_MERGE_DAILY_CAP_OUTLOOK_PERSONAL` | 100 |
| Microsoft 365 | Outlook with any other tenant | `MAIL_MERGE_DAILY_CAP_MICROSOFT_365` | 5,000 |

`get_send_budget` counts every recipient row of the connection's merges with
an `attempted_at` in the last 24 hours, whether or not the send was confirmed.
When the mailbox is at its cap, `frees_at` gives the time the next send fits.
`estimate_merge_finish` estimates when a merge finishes at
`MAIL_MERGE_SEND_INTERVAL_SECONDS` (default 3, at least 2 because Microsoft
365 accepts 30 messages a minute), across days when the merge is larger than
the remaining budget. A larger merge is allowed; it waits for budget rather
than being refused.

Test sends from the approval card are pending, so the budget counts only
merge sends.

## Sending

The `mail_merge.send` background job is the only sender
(`services/mail_merge/send_merge_chunk.py`). `queue_merge_send` queues it for
a merge. Each job sends at most 25 emails, or stops starting sends after
about 8 minutes, then queues the next chunk. Sends from one merge are
`MAIL_MERGE_SEND_INTERVAL_SECONDS` apart, give or take 30%.

Before each send, under the merge's row lock, the job checks that:

- It still holds its job lease.
- The merge is still `sending`, so a pause or cancel takes effect before the
  next email.
- The sender is still an active member of the workspace.
- The mailbox has budget left. Otherwise the next chunk waits until the
  oldest counted send leaves the 24-hour window.
- The Do Not Email guard doesn't refuse the address. An address listed after
  approval is `skipped`.

It then claims the next `pending` row with `FOR UPDATE SKIP LOCKED`, marks it
`sending` with `attempted_at`, and commits before calling the provider. Every
email has a pending audit event when it's claimed and a terminal one with its
outcome, both written in the same transaction as the row's status.

### Provider senders

Each mail provider contributes a `mail_merge` definition to its plugin: a
factory that opens a sender for the merge's personal connection, and the
scopes a merge needs. The sender creates a draft with one To address, sends
it, and checks a stored draft. The draft's IDs are committed before the send:

| Provider | Stored before the send | Not sent | Sent | Couldn't Confirm |
| --- | --- | --- | --- | --- |
| Gmail | Draft ID and thread ID | `drafts.get` finds the draft | The draft is gone and its thread holds a `SENT` message | The draft is gone and nothing in its thread was sent |
| Outlook | Immutable draft ID and `internetMessageId` | The draft ID opens a message with `isDraft` true | It opens with `isDraft` false | The draft ID opens nothing |

Gmail replaces the Message-ID of every email it sends, so its sender reads
the sent copy's Message-ID into `message_id_header` after the send. A
Gmail connection without `gmail.compose`, granted before that scope was
requested, pauses the merge for a reconnect before any send.

Both senders map their providers' throttling as rejected, so the row can wait
and the same draft is checked and sent later. Other tools keep the shared
error mapping. For the error shapes, see the Gmail client and
[Microsoft Graph](integrations/microsoft-graph.md#mail-merge-sends).

### Reconcile before any resend

A row left `sending` by a crash, a timeout, or a lost lease is settled at the
start of the next job, before anything else is sent:

- A row with no draft ID stopped before its draft existed and returns to
  `pending`.
- A draft that's still waiting returns the row to `pending`. A `pending` row
  that already has a draft is always checked again before it's sent, so a
  draft someone sent by hand isn't sent twice.
- A sent draft makes the row `sent`. Anything else makes it `unverified`.

When a send's response is lost, the job checks the draft at once. A draft
still waiting means the send failed, and the row is `failed`. If the check
also fails, the row stays `sending` for the next job.

### Stop rules

The job applies these rules:

| Event | Effect |
| --- | --- |
| The provider throttles a request | The row returns to `pending`; the next chunk runs after `Retry-After`, at most 15 minutes |
| The mailbox reaches its provider's daily limit | The row returns to `pending`, and the merge is `paused` with `stop_reason` `daily_limit` |
| Authentication or permission fails, or the connection is gone or lacks a scope | `paused` with `stop_reason` `reconnect` |
| Five settled rows in a row failed | `stopped` with `stop_reason` `repeated_failures` |
| Praxis reaches its own Gmail API quota (`403 dailyLimitExceeded`) | `stopped` with `stop_reason` `platform_quota` |
| The sender leaves the workspace, or is deactivated or deleted | `stopped` with `stop_reason` `sender_removed`; unsent rows stay unsent |
| The job fails on its last attempt | `stopped` with `stop_reason` `send_failed`; rows caught mid-send become `unverified` |

Deactivating or deleting a user stops their unfinished merges in every
workspace, alongside their schedules (`stop_user_mail_merges`). The job's
membership check before each send covers leaving one workspace.

## Settings

Every mail merge setting is listed in `apps/api/.env.example` and in
`deploy/gcp`, where `deploy.sh` checks each against the API's bounds:

- `MAIL_MERGE_DAILY_CAP_GMAIL_PERSONAL`, `MAIL_MERGE_DAILY_CAP_GOOGLE_WORKSPACE`,
  `MAIL_MERGE_DAILY_CAP_OUTLOOK_PERSONAL`, and
  `MAIL_MERGE_DAILY_CAP_MICROSOFT_365`: the daily caps in the previous table.
- `MAIL_MERGE_SEND_INTERVAL_SECONDS`: the pause between two sends of one
  merge.
- `MAIL_MERGE_MAX_RECIPIENTS`: the most rows one merge can have, at most 500.

## Pending

These parts aren't built:

- The `gmail_send_mail_merge` and `outlook_mail_send_mail_merge` tools, the
  approval card, and the required test send to the operator's own address.
  Test sends must be recorded where `get_send_budget` counts them.
- The progress card with Pause, Resume, Cancel, and a results download.
- Bounce matching. Gmail rows keep the sent copy's Message-ID, and Outlook
  rows keep the draft's, for when it's built.
