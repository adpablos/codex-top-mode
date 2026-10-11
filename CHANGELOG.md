# Changelog

User-visible changes integrated into the repository. Dates identify changes,
not a tagged release or evidence of live installation.

## 2026-10-11

- Renamed the project to Top Mode (repository `adpablos/top-mode`, skill
  `top-mode`). The private folder stays `~/.codex-top-mode` so saved setups
  keep working.
- Rewrote the README, AGENTS.md and skill in plain language around four jobs:
  set up, check, run and report. Top Mode now targets Codex, Claude Code and
  similar agents; announced Codex resets are an optional add-on with their own
  [guide](references/announcements.md). Removed the unimplemented cloud mailbox
  description.
- Added `scripts/usage_report.py`: a quota suggestion (unused weekly allowance
  near renewal, expiring saved resets) from Codex local logs, a native Codex
  payload or a saved Claude Code status line, and token totals per agent, model
  and effort from local Codex and Claude Code logs for run reports.
- Added a [fictional run report](examples/report.example.md).

- Added a private profile reference that setup saves and later sessions recover,
  with a short activation request, explicit profile replacement and refusal of
  Git worktree locations. Package updates preserve personal settings.

- Simplified first-time setup and the coordinator/status/stop explanation with
  an accessible diagram and fictional conversation. Distinguished included files,
  active work, announcement watch and saved reset reminders. Added a short agent
  entry point and moved maintenance/technical watch details to their guides.

- Added the portable profile/skill for bounded manual work and verified
  conditional preflight, with deadlines, ownership checks, explicit permissions
  and native quota stopping. Added the optional public watcher with partial
  discovery, quiet unchanged checks and replay protection ([PR #1](https://github.com/adpablos/codex-top-mode/pull/1)).
- Added the owner-dispatched read-only maintainer review workflow, including
  credential-output rejection and bounded publication. It requires a separately
  configured personal credential and real runtime verification; package users
  do not need it ([PR #2](https://github.com/adpablos/codex-top-mode/pull/2)).
- Defined a [portable run report](references/profile-contract.md#run-report)
  linking useful outcomes with sourced time, quota, model/effort, execution
  counts and tokens or explicit unknowns. No telemetry collector was added.
- Documented how a maintainer configures, dispatches and verifies the optional
  review workflow, including human credential entry and separate merge authority.
