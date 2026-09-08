# Repository agent instructions

Keep AGENTS.md focused on working rules, security boundaries, verification,
and links that tell an agent what to read for its task. Maintain implementation
details in the [documentation index](../README.md).

## Instruction layout

The repository uses one shared instruction source at each existing scope:

- Root AGENTS.md defines project-wide expectations and links to app guidance.
- `apps/api/AGENTS.md` defines backend conventions and domain reading triggers.
- `apps/web/AGENTS.md` defines frontend conventions and domain reading triggers.
- Root CLAUDE.md imports AGENTS.md so Claude Code uses the same rules.

App files explicitly apply alongside the root rules. Agents starting at the
root must read the relevant app file before editing. A task can span several
domains, so read each applicable reference, including shared integration
contracts and the provider-specific document.

Official sources checked on 8 September 2026.

## Codex and GPT-6 Astra

Codex discovers instructions from the repository root down to its working
directory. It uses at most one instruction file per directory, with
AGENTS.override.md taking precedence over AGENTS.md. Its default combined
project instruction limit is 32 KiB. Discovery stops at the working directory;
root-launched tasks therefore need explicit pointers to app instructions.
These are Codex loading rules, separate from the selected model's behaviour.
See [OpenAI's AGENTS.md guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

OpenAI describes GPT-6 Astra as more sensitive to instructions in skills and
repository files. It recommends auditing those instructions. Its guidance also
identifies tendencies towards clarification pauses and excessive verification
on small tasks. Keep scope, commit authorisation, writing style, and
proportionate checks explicit. See
[GPT-6 Astra behaviour](https://developers.openai.com/api/docs/guides/latest-model#gpt-6-astra-behavior).

## Claude Code and Claude Fable 5.1

Claude Code reads CLAUDE.md rather than discovering AGENTS.md directly.
Anthropic documents importing AGENTS.md through CLAUDE.md, which this
repository already does. Ancestor files load at startup; descendant files
load when Claude reads within their directories. Anthropic recommends keeping
CLAUDE.md below 200 lines, as a writing target rather than a truncation limit.
Imports still consume context; path-scoped rules can defer specialised
instructions. See [Claude Code memory](https://code.claude.com/docs/en/memory).

Anthropic recommends linking to detailed API documentation and removing
information an agent can discover from code. Keep non-obvious conventions,
commands, and common failure modes in the entry point. See
[Claude Code best practices](https://code.claude.com/docs/en/best-practices#write-an-effective-claude-md).

Fable 5.1's model guidance recommends clear task boundaries and completion
expectations. It also addresses unnecessary additions, excessive permanent
tests, and whole-file rewrites for small edits. Apply these through concise
shared working rules rather than copying a model's entire prompt guide into
the repository. See
[Claude Fable 5.1 prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-1).

## Maintain focused documentation

This repository applies the vendor guidance with the following conventions:

- Keep entry points comfortably below 200 lines and the combined Codex limit.
  This is a maintenance target, not a new automated gate.
- Put provider behaviour, settings, payload limits, and presenter details in
  the corresponding implementation document. Keep shared contracts in the
  shared guide and link to them from provider pages.
- Use ordinary Markdown links with explicit reading conditions. Avoid
  importing all detailed references into every session. The writing guide
  remains required reading for all writing, including comments and docstrings.
- Update the document that owns a behaviour when changing it. Update AGENTS.md
  when a working rule or navigation path changes.
- Keep architecture rationale in architecture notes. Link between rationale
  and implementation constraints instead of copying whole sections.
- Add nested instruction files only when a directory needs distinct working
  rules. File discovery depends on the agent application; do not assume a
  model ID changes which files are loaded.

## Verify instruction changes

Check local links, imports, document sizes, and preservation of security and
verification rules. Start fresh Codex sessions from the root and an app
directory, then ask which instruction sources apply. In Claude Code, inspect
`/context` and `/memory` and confirm the shared root instructions load.
Exercise a representative provider task to verify that the agent reads both
the shared integration guide and its provider reference before editing.

Static checks validate the documents; fresh-session checks validate actual
agent behaviour. Keep the distinction explicit when reporting verification.
