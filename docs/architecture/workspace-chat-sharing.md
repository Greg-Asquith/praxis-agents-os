# Workspace chat sharing

Chats have separate execution ownership and visibility. Every creation path
starts private. An active chat owner can share a direct, scheduled, or event
root chat with their team workspace, including when their role is read-only.
All active workspace members, including future members, can read its saved
transcript. A link identifies the workspace and chat; it grants no authority.
Personal workspaces and delegated child chats cannot be shared.

## Read and execution boundaries

Conversation detail and message reads use a dedicated read-access check.
Existing owner checks continue to protect replies, approvals, context, read
receipts, deletion, and delegated transcripts. Existing manager permission to
cancel runs remains independent of sharing. Viewer reads perform no execution,
provider fetch, approval-state recovery, or run reaping.

The shared transcript is ongoing saved content, not a snapshot. The API returns
the ordinary message contract with system instructions, reasoning, arbitrary
message metadata, and approval execution metadata removed. Completed tool
results and their published display metadata keep their existing payloads.
Calls without a saved result remain hidden, including calls awaiting approval.
Tools need no sharing-specific declarations or alternate result schema. Specialist results
can appear in the parent's answer; child transcripts retain owner-only access.

Saved answer text can include information obtained through personal
connections. Sharing deliberately publishes that saved text to the workspace.
It does not permit another provider fetch through the owner's credentials.
Files and Artifacts retain their independent access rules and stable links.

Shared chats reuse the ordinary transcript parser, message components, and tool
presenters. A read-only rendering context suppresses provider previews.
Saved links render normally; destination APIs enforce their own access rules.
The viewer route supplies saved messages without mounting
owner recovery, approval controls, or the message composer. There is no separate
shared-tool renderer or alternate display format.

Legacy conversation links redirect viewers to the shared-chat route. That route
uses the existing detail query and one paginated message query.

## Revocation and lifecycle

The chat owner can stop sharing. Workspace owners and admins can revoke an
existing share but cannot publish or discover another person's private chat.
Ownership does not transfer when the owner leaves. Shared chats remain readable
until sharing stops or existing deletion and retention rules remove them.
Former members lose access through the membership check.

Sharing changes lock the conversation row and commit visibility and a strict
audit record together. Repeating an authorised unchanged request emits no
additional event. After a manager revokes sharing, another request cannot
discover the private chat. Deletion uses the same conversation row lock.
Workspace row-level security remains unchanged; same-workspace owner privacy
is enforced by services.

Confirmed access loss clears the viewer's retained detail and transcript.
Refresh, focus, and reconnect reload saved content. Network failures can retain
previously loaded content with an error notice. Revocation cannot erase copied
text, downloaded files, or responses already delivered to a browser. Independent
workspace file access and previously issued download URLs are unaffected.

## Deferred participation

Shared viewers cannot send messages or approve actions. Multiplayer requires
separate decisions about attribution, credentials, budgets, approvals, removal,
read state, turn ordering, streaming, and delegated transcript inheritance.
