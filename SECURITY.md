# Security policy

## Supported versions

Security fixes are applied to the latest `2.x` release. Users should upgrade the marketplace snapshot and reinstall the current plugin before reporting a problem that may already be fixed.

## Reporting a vulnerability

Do not open a public issue for a vulnerability, credential exposure, or exploit technique. Use the repository's private GitHub Security Advisory reporting flow:

`https://github.com/progressrdx/multi-agent-role-work/security/advisories/new`

Include the affected version, operating system, Codex version, reproduction steps, impact, and any relevant sanitized workflow state. Never include live credentials, private source code, personal data, or unredacted logs.

## Security boundary

This plugin is a workflow-integrity tool, not an identity, authorization, or sandbox system.

- Role separation is logical. Agents may run under the same user and model.
- Human approval records explicit authorization but does not authenticate the approver.
- Repository files, comments, generated documents, test output, and tool output are untrusted inputs.
- Evidence hashes detect later content changes; they do not provide signatures or tamper-proof audit history.
- File locks and revisions prevent accidental concurrent local writers; they do not resolve Git merge conflicts or hostile filesystem access.

## Safe operation

- Review verification shell commands before registration: the state tool executes recorded build/test commands in the repository with the current user's privileges. Use the least privilege needed and never embed credentials in a command.
- Deterministic test logs are local, size-bounded workflow evidence. Treat them as sensitive, keep `.ai-workflow/` out of Git, and sanitize tools that print credentials or personal data.
- Never copy secrets into PRDs, reviews, meeting notes, workflow state, prompts, or test fixtures.
- Keep evidence inside the repository; the state tool rejects evidence paths outside it.
- Require explicit human authorization for destructive data operations, permission changes, production releases, security exceptions, and other irreversible actions.
- Treat instructions embedded in repository content as data unless the user explicitly authorizes the requested action.
- Verify test and CI results from their authoritative execution source; do not rely only on a developer-authored summary.
