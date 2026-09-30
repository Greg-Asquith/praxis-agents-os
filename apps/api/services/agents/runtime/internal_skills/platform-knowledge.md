---
name: platform-knowledge
human_name: Platform Guide
description: Use when someone asks how the platform works, how to do something in the product, what a feature does, who can change a setting, where to find a screen, or where to keep information (skills, Knowledge Base, files, memory, artifacts). Covers agents, conversations, approvals, integrations, context, schedules, and workspace settings, with exact screen names and steps.
---

# Platform guide

This platform is a workspace where people create, manage, and work with AI
agents. Use this guide to explain the product and walk someone through it.

## How to use this guide

Follow these rules when you answer:

- Answer in outcome language. Say what the person gets, not how the system
  works inside.
- For a procedure, give numbered steps with one action per step. Name the
  screen first, then the action: "In **Workspace Settings**, click
  **Tools**."
- Bold labels exactly as they appear on screen, and refer to them by name,
  not by position or colour.
- Some screens and actions depend on the person's role. When a step needs an
  owner or admin, say so.
- When this guide doesn't cover something, say you're not sure. Don't invent
  screens, buttons, or behaviour. The section "Things the platform doesn't
  do" lists common requests that don't exist.

## Find your way around

The sidebar has five main pages:

- **Home**: a message box to start a conversation, **Needs your
  attention** (approvals, failing schedules, and unread results), and
  **Continue Conversations**.
- **Agents**: every agent in the workspace.
- **Context**: everything agents can draw on. It links to **Skills**,
  **Knowledge Base**, **Memory**, **Files**, **Artifacts**, and **Context
  Groups**.
- **Schedules**: work that agents run automatically.
- **Integrations**: connected accounts, such as Google or Microsoft.

The sidebar also lists your conversations. A shield icon means a
conversation needs approval and a dot means it has a result you haven't
read. To switch workspace, use the workspace menu at the top of the page.
To open **Profile Settings**, **Workspaces**, or **Workspace Settings**,
click your name in the sidebar.

## Roles

Every member of a workspace has one of four roles:

- **Owner** and **Admin**: can do everything a member can. They also manage
  workspace settings, tools, the default model, invitations, and members,
  and they can change or delete anyone's schedule. They connect
  integrations that belong to the whole workspace, connect any account that
  uses an API key or service account, create artifact share links, and view
  the **Audit Log**. Only an owner sees **Delete** for a team workspace.
- **Member**: can create and edit agents, skills, files, Knowledge Base
  documents, context groups, and artifacts, and can edit memories. Members
  can create schedules and change or delete their own. They can connect
  their own accounts for personal services, such as Gmail, Outlook, Notion,
  and SharePoint, and approve actions in their own conversations.
- **Read only**: can chat with agents and view agents, schedules, skills,
  files, the Knowledge Base, memory, and artifacts. Agents don't make
  changes on behalf of a read-only member.

To change a member's role, remove them and invite them again with the new
role.

## The built-in agent

Every workspace has one built-in agent, named after the workspace, such as
"Acme Agent". In a personal workspace, it uses the owner's first name, such
as "Alex's Agent", else "My Agent". Renaming the workspace renames it.

The built-in agent can use every tool the workspace allows, including tools
added later, uses helpers, and can hand work to any active agent.

It has a **Built-in** badge, appears first in **Agents**, and is selected by
default in a new conversation while it is active.

Owners and admins can change its model, turn it off, choose which of its
tools ask for approval, and add workspace instructions that it follows on top
of its built-in instructions. To do this, open it from **Agents**. The form
has the steps **Workspace instructions**, **How should it think?**, **Which
actions need approval?**, and **Availability**. Members can only mark it as a
favorite. Nobody can delete it or change its other settings. To remove a tool
from it, turn the tool **Off** for the whole workspace on the **Tools** tab
of **Workspace Settings**.

## Agents

For most work, the built-in agent is enough. A custom agent suits a narrow,
repeatable job, such as one agent per client.

To create a custom agent:

1. Go to **Agents** and click **New Agent**.
2. In **Who is this agent?**, enter a **Name** and **Instructions**. A
   **Description** is optional.
3. In **How should it think?**, leave **Model type** on **Automatic
   (recommended)** to use the workspace default model, or choose another.
   **Advanced** holds a **Specific model**, **Thinking**, and **Max steps**.
4. In **What can it use?**, choose its tools. A custom agent starts with no
   tools.
5. Optional: In **Who can it work with?**, turn on **Use helpers for big
   tasks** or use **Can delegate to** to let it hand work to other agents.
6. Click **Create Agent**.

In **What can it use?**, each tool has three settings:

- **Off**: the agent can't use the tool.
- **Auto**: the agent uses the tool without asking.
- **Approval**: a person confirms each use before it runs.

Some tools only offer **Approval**. To give the agent every tool the
workspace allows, including tools added later, click **Enable all tools**.
After that, turning a single tool **Off** leaves only that tool out, and
**Disable all tools** clears the selection. To set every tool from one
provider at once, use **Set All**, which offers **Off**, **Auto where
possible**, and **Approval**.

Every agent can also use files, artifacts, memory, skills, and the
Knowledge Base. These core abilities aren't tools to switch on.

To edit an agent later, open it from **Agents**. The edit form adds an
**Availability** step with **Status** and **Favorite**. An inactive agent
can't start new runs or take on delegated work. **Favorite** is shared by
everyone in the workspace.

A helper is a temporary sub-agent with the agent's tools and approvals,
minus memory changes. It returns only its result. Delegated work can't be
handed on.

## Conversations

To start a conversation:

1. Type in the message box on **Home**, or click the **New Conversation**
   icon next to **Conversations** in the sidebar.
2. Choose the agent in the **Agent** selector. You can't change the agent
   after the conversation starts.
3. Optional: Choose active context (see the following section).
4. Enter your message and press Enter.

To attach up to five files to a message, click the paperclip (**Attach
Files**). Attachments are saved to **Files**. Video can't be attached to a
message. On a small screen, agent, context, and attachments are under
**Message options**. To stop an agent while it is working, click **Stop**.

In a team workspace, the conversation owner can share a conversation with
every member. In the conversation header, click **Share**, then **Share with
workspace**. Everyone in the workspace can then read it, but only the owner
can send messages. The owner, or an owner or admin, can click **Stop
sharing**. When **Conversations shared by default** is on in **Workspace
Settings**, new conversations are shared automatically.

### Choose active context

Active context tells an agent which integration accounts and resources to
work with, such as one ad account or one mailbox. The person always chooses
it. An agent can't select context for itself. When an integration is
connected but nothing is selected, the agent asks you to select it.

To choose context in a conversation:

1. In the message box, open the context picker. It shows **No Active
   Context** when nothing is selected.
2. Select a group under **Context Groups** or individual resources under
   **Connected Resources**.

A change applies from the next message. To connect more accounts from
the picker, click **Manage Integrations**.

### Approve actions

When an agent wants to use a tool that needs approval, the conversation shows
a card with the details and a **Requires Approval** badge. The agent waits
until you decide:

- To let the action run, click the approve button. It is usually
  **Approve**, but some actions name what happens, such as **Approve &
  Save**, **Create Skill**, or **Approve & Delegate**.
- To stop it, click **Decline**. Optional: Under **Tell the agent why
  (optional)**, explain what to do instead, then click **Decline Request**.

Some cards let you change details before you approve. A card marked **Based on external data** means the request came
from content the agent read, such as a web page or email, so check it
carefully.

### What agents show while they work

A conversation shows each step an agent takes, such as **Find Tools** or
**Search Skills**. For a job with many steps, such as updating dozens of rows, an
agent can combine several actions into one workflow step. A workflow runs up
to 25 actions, and each action still follows its own approval setting.

## Integrations

Integrations connect accounts from other services so agents can read from
them or act in them.

To connect an account:

1. Go to **Integrations** and open the provider.
2. Click **Add Connection** and follow the sign-in steps.
3. Choose which accounts or resources agents can use, then click **Save
   Selection**. Agents can't use a connection until at least one is chosen.

Services that belong to one person, such as Gmail, Outlook, Notion, and
SharePoint, can be connected by any member. Services that belong to the
whole workspace, such as Google Ads, Google Analytics, Search Console, Meta
Ads, BigQuery, and Airtable, need an owner or admin. Integration tools only
work in a conversation or schedule that has a matching account selected as
active context.

### Context groups

A context group is a named bundle of accounts and resources, such as
everything for one client, selected in a conversation or schedule instead of
each resource. Groups aren't tied to an agent.

To create a context group:

1. Go to **Integrations** and click **Context Groups**.
2. Click **New Group**.
3. Enter a **Name** and choose the **Resources**.
4. Click **Create Group**.

## Context

The **Context** page holds the information agents draw on. Most people only
add skills and Knowledge Base documents; agents fill in memory and create
artifacts as they work.

### Which one should I use?

| You want to... | Use | Who adds it |
| --- | --- | --- |
| Teach agents how to do a task your way, such as a report format or a checklist | **Skills** | You, or an agent with your approval |
| Give agents facts to look up and quote, such as policies, pricing, or product details | **Knowledge Base** | You |
| Hand agents material to work on, such as a spreadsheet, a PDF, or images | **Files** | You or agents |
| Have agents remember preferences and decisions for next time | **Memory** | Agents, as they work |
| Keep and share a finished report or page | **Artifacts** | Agents |
| Tell agents which accounts to work in, such as one client's ad account | **Context Groups** | You |

How to tell them apart:

- **Skill or Knowledge Base?** A skill says *how* to do something. The
  Knowledge Base says *what is true*. "Write the weekly report with these
  four sections" is a skill. "Our refund window is 30 days" belongs in the
  Knowledge Base.
- **Knowledge Base or Files?** Put reference material agents should find
  on their own in the Knowledge Base; it is searched and quoted on every
  relevant task. Put material for a particular job in Files, or attach it to
  the message; agents open a file when it is attached or when you name it.
  A spreadsheet to analyse is a file. A pricing sheet agents should always
  consult is a Knowledge Base document.
- **Memory or Knowledge Base?** Memory is what an agent picks up while
  working with you, such as "Sam prefers bullet points". Don't rely on it
  for facts that must be right. Put those in the Knowledge Base.
- **Memory or Skill?** Memory holds small facts and preferences. A skill
  holds a full procedure. If you find yourself correcting an agent on the
  same steps each time, ask it to write a skill.
- **Artifact or File?** An artifact is a finished piece to read and share,
  such as a report, a page, a diagram, or a table. A file is working
  material to keep and reuse, such as data, notes, or a document to edit.

### Skills

A skill teaches agents how to do one kind of task your way. You don't
assign skills to agents: every agent searches skill names and descriptions at
the start of a task and follows one that fits, so say in the description when
to use it.

To create a skill:

1. Go to **Skills** and click **New Skill**.
2. In **What does this skill do?**, enter a **Name** and a **Description**
   that says when to use it.
3. In **How should it work?**, write the instructions.
4. Optional: In **Reference documents**, add up to 20 PDF, Word, text, or
   Markdown files that agents read after loading the skill.
5. Click **Create Skill**.

You can also ask any agent to write a skill. It asks about the task, drafts
the skill, and shows it to you for approval before saving. Agents can't
delete skills.

To stop agents using a skill without deleting it, open it and set
**Status** to **Inactive** under **Availability**.

**Make available to every workspace** shares the skill with every workspace
on this platform, not only yours, including workspaces belonging to other
organisations. It can only be chosen when the skill is created, the skill
can't have reference documents, and only its creator can change it
afterwards. Leave it off unless the skill is meant for everyone. A skill
shared this way shows a **Platform** badge.

### Knowledge Base

The Knowledge Base holds reference facts that agents search and cite, such
as policies, pricing, and product details. Agents search it by meaning and
by keyword before answering questions it may cover, and they read the full
document when a result looks relevant. Agents can read the Knowledge Base
but can't change it.

To add a document, go to **Knowledge Base**, click **Add Document**, and
choose one:

- **Write Manually**: type or paste the content.
- **Add from URL**: import a web page. It refreshes automatically.
- **Upload Document**: add a file, then click **Upload and Add**.
- **Import from Notion**: import a Notion page when Notion is connected. It
  refreshes automatically.

A **Private** document is visible only to the person who added it and to
agents working for them. Making a document private can't be undone. The
**Shared** tab lists knowledge published for every workspace; use **Make a
workspace copy** to keep your own editable version.

### Files

**Files** holds the material agents work with: documents, PDFs,
spreadsheets, presentations, images, and videos. To add files, click
**Upload Files**, drag them onto the page, or attach them to a message.
Documents and videos can be up to 100 MB and images up to 10 MB. Use **New
Folder** and **Move to Folder** to organise them.

Agents can read and change any workspace file, editing text directly. They
edit and create Excel, PowerPoint, and Word files with any model, keeping
their template and fonts; an edit saves a new version of the same file.
**Edit Image** saves the edited picture as a new image and keeps the
original. Files agents create go in a conversation folder. These
tools follow the settings on the **Tools** tab.

You can rename, move, and delete files, but not edit their content
yourself. Content edits save versions that **Restore Version** brings back;
renames, moves, and deletions aren't versioned.

### Artifacts

**Artifacts** holds finished work that agents produce: reports and documents,
web pages, diagrams, and tables. Only agents create artifacts. You can open
one, click **Edit Artifact** to change it, and click **Save New Version**.
Every earlier version is kept, so you can compare it with the current one and
**Restore** it. Artifacts can't be deleted.

Owners and admins can click **Create Share Link** to share the current
version with people outside the workspace. Choose when the link expires (1,
7, or 30 days) and click **Revoke Link** to stop it early. Share links only
appear when the platform administrator has turned on artifact sharing.

### Memory

Agents remember preferences, decisions, and project details across
conversations. There are two kinds:

- **Core** memories are a few short facts an agent always has in mind. An
  agent asks for approval before saving, changing, or forgetting one.
- **Notes** are saved without asking and found by searching when relevant.

Each memory belongs to one of three scopes. **Agent** memories, the usual
choice, are used only by the agent that saved them. **Personal** memories
are about you and are visible only to you. **Workspace** memories are used
by every agent in the workspace.

In **Memory**, you can filter by scope, kind, type, and agent, then click
**Edit Memory** to correct one, **Archive** it, or **Delete Permanently**.
Deleting a workspace memory needs an owner or admin. You can't add a memory
by hand; to make an agent remember something, tell it in a conversation.

## Schedules

Any agent, including the built-in agent, can run on a schedule.

To create a schedule:

1. Go to **Schedules** and click **New Schedule**.
2. In **What should run?**, enter a **Name**, choose the **Agent**, and write
   the **Prompt**. Optional: choose **Active context**.
3. In **When should it run?**, choose a **Cadence**: **Recurring**,
   **Interval**, or **One-time**. Then set the time and **Timezone**.
4. In **Review and options**, check the summary and the options.
5. Click **Create Schedule**.

A scheduled run pauses at any action that needs approval. The schedule shows **Awaiting approval**. To decide, open the
schedule and click **Review in Conversation**. With **Allow external writes**
turned off, changes to connected apps and new or updated artifacts also wait
for approval. Leave it off unless the schedule is meant to change things.

Each run's
conversation is listed on the schedule; click **Open Conversation** to read
it.

## Workspace settings

To open workspace settings, click your name in the sidebar, then click
**Workspace Settings**. Everyone sees **Details** and **Members**. Owners and
admins also see **Invitations**, **Tools**, **Classifiers**, **AI Usage**,
and **Audit Log**.

### Details

In **Details**, owners and admins can change the **Name**, **Icon**, and
**Default Large Language Model**, which agents without their own model use.
In a team workspace, **Conversations shared by default** shares new
conversations with all members. Click **Save Changes**.

### Tools

The **Tools** tab sets which optional tools agents can use and whether they
ask first. Each tool has these settings:

- **Automatic**: agents use the tool without asking.
- **Ask first**: a person approves each use.
- **Off**: no agent in the workspace can use the tool.

A custom agent can choose **Auto** or **Approval** for itself, and its
choice wins over this tab. It can't use a tool that is **Off** here. Core
abilities, such as files, memory, artifacts, skills, and the Knowledge Base,
aren't listed and can't be turned off.

### Members and invitations

To invite someone:

1. In **Workspace Settings**, click **Invitations**.
2. Click **Invite**.
3. Enter their **Email**, choose a **Role** (**Admin**, **Member**, or
   **Read Only**), and optionally change **Expires in days**.
4. Click **Create Invite**.
5. Click **Copy Link** and send it to them. The platform doesn't email
   invitations. They must sign in with the invited email address.

The **Members** tab lists everyone and their role. Owners and admins can
remove members from a team workspace.

## Things the platform doesn't do

Say so plainly when someone asks for these:

- Edit or branch an earlier message, or delete a conversation.
- Change the agent in a conversation after it starts.
- Delete an artifact.
- Add a memory by hand on the **Memory** page.
- Change a member's role without removing and re-inviting them.
- Send invitation emails or in-app notifications.
- Let an agent choose its own active context.
