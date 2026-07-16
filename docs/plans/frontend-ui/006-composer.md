# Plan 006: Composer redesign

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — submit, stop, attachment upload, and drag-drop flows
  all live here; the restyle must keep every handler and state intact.
- **Depends on**: 001 (tokens), 003 (agent identity for the create-mode
  picker). Coordinates with 004 on the shared `max-w-4xl` column (widened
  from the original 48rem target after maintainer QA of a real transcript).

## Goal

Replace the form-like composer with the reference's floating card: one
rounded bordered surface containing a borderless textarea, a bottom
control row (plus-button for attachments left; muted model label and a
circular accent send button right), and a small centered disclaimer line
beneath. Same behavior, completely different feel.

## Current state (verified at `158de0b`)

`src/features/conversations/components/conversation-composer.tsx`, mounted
in the route footer (`conversation-route.tsx:185-202`, and
`new-conversation-route.tsx:70-78` for create mode).

- Root `<form className="flex flex-col gap-3">` + `FieldGroup` (291–292).
- Create mode: full-width agent `Select` above the textarea (296–328); no
  model picker anywhere — model is agent-bound.
- Textarea: standalone bordered `Textarea` (`max-h-52 min-h-12 resize-y`,
  372–375) inside a drag-ring wrapper (359–363); drop overlay with
  `UploadCloudIcon` (389–399).
- Bottom bar (403–454): left hint "Enter sends, Shift+Enter adds a line.";
  right cluster = paperclip ghost button, conditional Stop button, and a
  labeled **Send** button with `SendIcon`.
- Attachments as chips above the textarea (339–353;
  `attachment-chip.tsx`).
- Enter submits / Shift+Enter newline (236–241). Errors as destructive
  `Alert` (332–337).

## Decisions taken

1. **One card.** The border moves from the `Textarea` to a wrapper card;
   the textarea becomes borderless/transparent inside it. Focus ring
   renders on the card (`focus-within`), not the textarea.
2. **Model label, not model picker.** Show the active agent's resolved
   model as muted text in the control row (data is already available in
   create mode via the selected agent; in turn mode via the conversation's
   agent — verify what the conversation query exposes; if the model name
   is not available in turn mode, show nothing rather than fetching more).
3. **Send becomes a circular accent icon-button** (`ArrowUpIcon`), the
   page's one `default`-variant button. Stop replaces it in place while
   streaming (same slot, `CircleStopIcon`, `outline`) — not two buttons
   side by side.
4. **The keyboard hint line goes away.** Enter-to-send is convention; the
   hint moves to the textarea `aria-description` and the send button
   tooltip-less `title`. The freed line becomes the disclaimer.
5. **Disclaimer copy**: "Agents can make mistakes. Review important
   results." — centered, `text-muted-foreground text-xs`, below the card.
   (Reference has an equivalent line; ours names our concept, "agents".)
6. **Create-mode agent picker moves into the control row** as a compact
   inline select (left of the model label): `AgentIdentityIcon` + name +
   chevron, ghost-styled trigger. The full-width select above the card
   disappears; drafting and choosing the agent happen in one surface.

## Steps

### 1. Card structure

Rebuild the composer render tree (handlers untouched):

```
<form>                                   flex flex-col gap-2
  [error Alert]                          unchanged
  <div card>                             bg-card rounded-2xl border shadow-xs
                                         focus-within:border-ring/60
                                         focus-within:ring-3 focus-within:ring-ring/20
                                         + existing isDraggingFiles ring classes merged here
    [attachment chips row]               px-3 pt-3 (only when attachments exist)
    <Textarea>                           border-0 bg-transparent shadow-none px-4 py-3
                                         focus-visible:ring-0 min-h-12 max-h-52 resize-none
    <div controls>                       flex items-center gap-1 px-2.5 pb-2.5
      attach button                      ghost icon (PlusIcon, aria-label="Attach files")
      [create mode: agent select]        compact ghost trigger, see step 3
      <spacer flex-1>
      [model label]                      text-muted-foreground text-xs truncate
      send/stop slot                     see step 2
  <p disclaimer>                         text-center text-muted-foreground text-xs
```

Keep the hidden file input, drag handlers, and drop overlay exactly as
they are (overlay radius follows the card: `rounded-2xl`). `resize-y` →
`resize-none`: manual resize fights the card look; `max-h-52` still caps
growth. The route footers (`conversation-route.tsx:193-194`,
`new-conversation-route.tsx`) drop to `pb-4 pt-2` so the card floats near
the canvas bottom edge, column `max-w-4xl` matching plan 004.

### 2. Send / stop slot

One slot, `size-8 rounded-full` icon button:
- idle: `default` variant, `ArrowUpIcon size-4`, `aria-label="Send"`,
  disabled exactly per the current `canSubmit` logic;
- streaming: `outline` variant, `CircleStopIcon` (spinner state per the
  existing stop-pending logic), `aria-label="Stop"`.
Reuse the existing handlers verbatim; only the presentation merges the
two buttons into one slot.

### 3. Create-mode agent picker

Restyle the existing `Select` (keep base-ui `Select` + items — same
component, new trigger styling): trigger = ghost `h-7 rounded-md px-2
gap-1.5 text-sm` showing `AgentIdentityIcon` (`sm`) + agent name +
`ChevronDownIcon size-3.5`. `AgentSelectItem` gains the identity icon
(may already have it if plan 003 step 3 landed — check). Label the
control for a11y (`aria-label="Agent"`); the old block-level
`FieldLabel` disappears with the old layout.

### 4. Attachment chips

`attachment-chip.tsx`: soften to match the card — `bg-muted/60 border-0
rounded-lg`; keep spinner/remove behavior.

### 5. Verify

- `pnpm check` passes.
- Live QA, both modes (existing conversation + /conversations/new), both
  themes: type/submit via Enter and via button; Shift+Enter newline;
  attach via button and via drag-drop (overlay shows, chips render,
  uploading state disables send); stop during a stream; create mode:
  pick agent from the inline picker, model label updates; read-only
  delegated transcripts still show the lock footer instead of the
  composer; error alert renders inside the layout without breaking the
  card.
- Keyboard-only pass: tab order textarea → attach → agent picker →
  send; focus visible on the card and each control.

## STOP conditions

- Turn-mode model label needs a new query or api change — omit the label
  in turn mode instead (decision 2), and note it; do not add fetches.
- Any submit/upload/stop handler would need behavioral change to fit the
  layout — stop and report.
