# Choose between skills, files, the Knowledge Base, and memories

Praxis provides four ways to give agents context. Choose the one that matches
how you want the agent to use the information:

| Goal                                                                   | Use                |
| ---------------------------------------------------------------------- | ------------------ |
| Follow instructions or a repeatable process                            | **Skill**          |
| Read, edit, or create a specific document                              | **File**           |
| Find shared reference information when relevant                        | **Knowledge Base** |
| Retain preferences, decisions, or project context across conversations | **Memory**         |

## Skills teach an agent how to do something

A skill contains instructions for a repeatable task. For example, a skill can
define how to write a weekly report, qualify a sales lead, or format customer
emails.

Create a skill once, then assign it to the agents that need it. An agent sees a
short description first and loads the full instructions only when the task
requires them. A skill can also include supporting documents, such as a report
template or style guide.

Super admins can also publish a platform skill to every workspace. Platform
skills contain instructions only, are marked **Platform** in the Skills list,
and can be changed only by a super admin. Workspace members can assign them to
agents but cannot edit or delete them.

Use a skill if you repeat the same instructions in several conversations. For
example, create a skill when every customer onboarding email
must follow the same structure.

## Files give an agent a specific document

Files store documents in your workspace, including spreadsheets, PDF files,
reports, and images. Attach a file to a conversation when you want an agent to
read or change that document. Agents can also create files.

Praxis saves each change as a separate revision. You can review earlier
revisions and restore workspace files when needed.

Shared files are published by super admins for every workspace. In **Files**,
use **All**, your workspace name, or **Shared** to choose which files appear,
and **Search files** to find a file by name in any folder. Folders and files share
one list, newest first. Workspace editors can drop files anywhere on the page
to upload them. Open a shared file to view or download it. For a supported
document or image,
**Add to chat** opens a new chat with the file ready for your message.

Workspace editors can select **Make a workspace copy** for independent changes.
The copy receives no later platform updates. Super admins can use **Upload Files**
in the **Shared** tab. Uploads become available in every workspace automatically
after processing succeeds. The Shared tab shows processing files to super admins.
Uploads in **All**, your workspace tab, or a folder stay in your workspace.

Only super admins can withdraw a platform original through the management API.
Withdrawal blocks future reads, but cannot recall downloaded content or local copies.

Use a file when the task concerns a specific document. Examples include
summarizing a PDF file, correcting a spreadsheet, or turning meeting notes into
a proposal.

## The Knowledge Base stores reference knowledge

The Knowledge Base is a searchable reference library for your workspace and
platform knowledge shared with every workspace. It can contain product
details, policies, pricing, frequently asked questions,
and client information.

Every agent in the workspace can search shared entries when a task requires
them. Add an entry by uploading a document, importing a web page, or writing
the content in Praxis. Mark an entry as private when only you may access it.

Use the Knowledge Base when agents need to find the information across many
conversations. For example, add a refund policy so agents can use it when they
answer customer questions.

### Use shared knowledge

In **Knowledge Base**, use **Shared** to find documents published for every
workspace. **Platform** badges identify them in lists and search results.
If you can edit workspace content, select **Make a workspace copy** to make
independent changes. The copy defaults to **Private** and receives no future
updates from the shared document.

Super admins can add manual entries and upload documents in **Shared**. After
processing, review the document and select **Publish** to make it available in
every workspace. Withdraw a published document before editing it.

### Choose between a file and the Knowledge Base

Use a file to work on a document in a conversation. Use the Knowledge Base to
make reference information searchable across the workspace.

When you upload a document through the Knowledge Base, Praxis also stores it
in Files. This keeps the source document available for later work.

### Choose between a skill and the Knowledge Base

Use a skill for instructions about how an agent performs a task. Use the
Knowledge Base for facts that an agent may need while performing a task.

For example, "Start every proposal with a one-paragraph summary" belongs in a
skill. "Our standard proposal turnaround is five business days" belongs in the
Knowledge Base.

## Memories retain useful context over time

Memories store preferences, decisions, and ongoing project context across
conversations. Agents can save durable core memories and searchable notes.

In **Memories**, you can review saved information, correct it while preserving
revision history, archive it, or permanently delete it.

Use a memory for information that develops through your work with an agent.
Use the Knowledge Base for shared reference material that applies across the
workspace.
