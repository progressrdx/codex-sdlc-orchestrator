# Threat model

## Scope

The plugin coordinates Codex roles and maintains file-backed SDLC state in a user-selected repository. It can guide Agents that read files, run commands, write code and documents, and invoke external tools authorized by the user.

It does not provide operating-system isolation, independent identities, cryptographic approval, secret storage, CI/CD authorization, or enterprise audit controls.

## Assets

- Source code, tests, configuration, and project data.
- Requirements, designs, reviews, approvals, and meeting records.
- Workflow state and its history.
- User authorization and external service credentials available to Codex.

## Trust boundaries

1. User instructions and explicit authorization.
2. Codex coordinator and delegated role Agents.
3. Repository content, including documentation and code comments.
4. Local commands and their output.
5. External services such as GitHub, CI, issue trackers, and deployment systems.

Repository content and external output are untrusted. A role label is not an authenticated identity.

## Threats and mitigations

### Prompt injection in repository content

An attacker may place instructions in a README, code comment, fixture, generated document, or issue. Treat embedded instructions as evidence to analyze, not authority. Only the user and applicable system policy may authorize actions.

### Fabricated or weakened verification

A developer may modify tests, provide a misleading summary, or manufacture evidence. The state tool executes recorded build/test commands, binds successful exit metadata and a bounded log hash to the tested source, and rejects commands that alter product files. Testing still uses an independent role because an exit code cannot prove that the chosen tests are sufficient. Developer self-test cannot satisfy independent acceptance.

### Verification command execution

A malicious or mistaken command can access anything available to the current user. Commands are explicit workflow inputs, run only during verification, have per-command timeouts, fail fast, and write local logs without echoing full output into model context. This is not a sandbox. High-risk repositories should execute verification in a container or trusted CI and avoid commands containing secrets.

### Evidence reuse or mutation

One file may be reused for multiple roles or changed after approval. The state tool rejects reused review hashes, rechecks indexed evidence hashes at gates, snapshots role verdict hashes in meeting records, and binds human approval to current meeting and decision hashes.

### Path escape

An Artifact path may point outside the selected repository. Evidence paths are resolved and required to remain under the repository root.

### Concurrent or interrupted state writes

Two processes may update state simultaneously, or a process may stop during a write. Mutations use a cross-process lock, optimistic revision check, flushed temporary file, and atomic replacement.

### Forged role or human identity

Agents share the user's execution environment, and approval evidence is not cryptographically signed. This remains a residual risk. High-assurance environments must integrate an external identity and approval system.

### Secret leakage

Secrets may enter prompts, documents, meetings, logs, or Git history. The plugin does not store secrets intentionally. Agents must redact sensitive values and avoid persisting them in workflow artifacts.

### Destructive or high-impact actions

AI reviewers may agree on an unsafe change. Configure human checkpoints for destructive data changes, permissions, production releases, security exceptions, and other irreversible actions.

### State tampering and Git conflicts

A user with filesystem access can edit state or artifacts, and Git merges can create semantic conflicts. Schema validation catches malformed state, but not authorized malicious edits. Review repository history and rerun affected gates after conflict resolution.

## Residual risks

- Correlated model errors across nominally independent roles.
- Malicious users or processes with repository write access.
- Compromised external tools or forged external output.
- Incorrect but well-formed documents and approvals.
- Platform-specific filesystem behavior outside tested environments.

Use an external sandbox, identity provider, protected branches, signed commits, CI enforcement, and deployment approvals when stronger assurance is required.
