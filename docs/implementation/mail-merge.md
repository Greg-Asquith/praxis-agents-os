<!-- docs/implementation/mail-merge.md -->

# Mail merge

A mail merge sends one personal email to each person on a list, from the
operator's own Gmail or Outlook mailbox, after one approval. Each email has one
recipient, and its placeholders are filled in mechanically from that person's
row. Merges are for Google Workspace and Microsoft 365 mailboxes; personal
Gmail and Outlook.com accounts keep lower caps as a safe default.

**Status:** pending. The records, template rendering, recipient checks, and
sending budget described on this page are implemented as backend services. No
agent tool, approval card, background sender, or route uses them yet, so an
operator can't start a merge.

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

- Provider senders for Gmail and Outlook. Both send through a draft whose
  IDs are stored before the send, so Praxis can tell after a crash whether
  the email went:
  - **Outlook:** the stored draft ID is immutable and follows the email
    into Sent Items. `isDraft=true` means not sent; `isDraft=false` means
    sent.
  - **Gmail:** Gmail gives the sent copy a new Message-ID and message ID,
    but keeps the draft's thread. A draft that still exists means not
    sent; a missing draft with a `SENT` message in the stored thread means
    sent; anything else is Couldn't Confirm and is never resent. Gmail
    connections request `gmail.compose` for this; a connection made before
    that permission was added must reconnect before it can send a merge.
- On Microsoft 365, going over the daily limit arrives as a bounce after a
  successful send, not as an error, so the sending budget is the guard
  that keeps a mailbox under its limit.
- The `mail_merge_send` background job, which re-checks the Do Not Email
  guard, the sender's membership, and the budget before each send.
- The `gmail_send_mail_merge` and `outlook_mail_send_mail_merge` tools, the
  approval card, and the required test send to the operator's own address.
- The progress card with Pause, Resume, Cancel, and a results download.
