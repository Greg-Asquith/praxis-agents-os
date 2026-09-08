# Documentation index

Start with the reference for the area you are changing. Implementation guides
describe maintained behaviour and constraints; architecture notes explain the
design decisions behind them. Read the relevant app's AGENTS.md first.

## Development and operations

Use these references for repository setup and maintenance:

- [Project overview](implementation/project-overview.md): processes and implemented domains.
- [Local development](implementation/local-development.md): services, tests, and live evaluations.
- [Agent instructions](guides/agent-instructions.md): instruction discovery and documentation maintenance.
- [GCP deployment](../deploy/gcp/README.md): bootstrap, deployment, and environment configuration.

## Implementation references

Use these references before changing the corresponding behaviour:

| Area | Reference | Related design |
| --- | --- | --- |
| Database roles, tenancy, and migrations | [Database](implementation/database.md) | [Threat model](architecture/threat-model.md) |
| Authentication, encryption, and audit | [Security](implementation/security.md) | [Governance](architecture/governance.md) |
| Runs, schedules, context, and recovery | [Agent runs](implementation/agent-runs.md) | [Runtime](architecture/agent-runtime.md), [streaming](architecture/agent-turn-streaming.md) |
| Registration, tool results, and approvals | [Tool dispatch](implementation/tool-dispatch.md) | Governance |
| Nested execution and transcript replay | [Code Mode](implementation/code-mode.md) | [Code Mode design](architecture/code-mode.md) |
| Third-party connections and tools | [Integrations and provider references](implementation/integrations/README.md) | [Provider packaging](architecture/integration-packaging.md) |
| Model routing and provider clients | [Model providers](implementation/model-providers.md) | Runtime |
| Native fetch, code, classification, and images | [Native tools](implementation/native-tools.md) | Governance |
| Worker admission, leases, and shutdown | [Workers](implementation/workers.md) | Runtime |
| Usage recording and cost estimates | [AI usage](implementation/ai-usage.md) | Governance |
| Storage, uploads, and file references | [Storage and files](implementation/storage-and-files.md) | [Agent context](architecture/agent-context.md) |
| Knowledge Base imports and source refresh | [Knowledge sources](implementation/knowledge-sources.md) | Agent context |

## Operator guides and other design notes

These documents cover product use and additional architectural decisions.
Check each architecture note's implementation status before treating a design
as available product behaviour:

- [Skills, files, knowledge, and memories](guides/skills-files-knowledge-memories.md)
- [Microsoft Entra app registration](guides/microsoft-entra-app-registration.md)
- [Inbound integration events](architecture/integration-events.md)
- [Internal applications](architecture/internal-applications.md)
