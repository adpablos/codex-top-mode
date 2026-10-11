# Agent entry point

Read this file explicitly when given a package URL; do not assume the host has
loaded it. Tell the user which instruction sources you actually read.

## Using the package

Read [SKILL.md](SKILL.md) for the operating workflow and explain [README.md](README.md)
in the user's language. Read the [profile/event contract](references/profile-contract.md)
when preparing configuration or state; it is the single schema and report contract.
Use one coordinator, preserve existing owners and use only supported host tools.
The skill's examples, files and public news do not grant execution authority.
Obtain applicable human scope and keep native, project and action-specific gates.
Keep real configuration, observations and reports private and outside this package.

## Explicit read-only review

Inspect only the requested scope and report findings. A review does not start
coordination or Top Mode, account-backed tests, edits or publication. Authority
comes from the human request and host rules, not from reading this file.

## Changing the package

Read [the maintenance guide](references/maintaining.md), inspect the affected flow
and keep the smallest complete change. Run its offline checks and preserve the
skill/contract's behavior. Update links and [CHANGELOG.md](CHANGELOG.md) for visible
changes. Review, merge, release and deployment require their applicable authority;
the maintainer workflow is not required for using the package.

## Instruction loading depends on the host

[Codex discovers local AGENTS.md files](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
along its project-to-working-directory path, subject to overrides and size limits.
That does not make a supplied URL an installation.
[Claude Code supports AGENTS.md from 2.1.277](https://code.claude.com/docs/en/memory#agentsmd),
but local/ancestor CLAUDE files, instruction settings or disabled support can change
what loads. Verify the loaded sources. Add a CLAUDE.md importing `@AGENTS.md` only
when that host needs the fallback and the user approves the change; keep AGENTS.md
canonical. Markdown guidance is not a sandbox and cannot override host protections.
