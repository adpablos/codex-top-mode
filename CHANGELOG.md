# Changelog

User-visible changes integrated into the repository. Dates identify changes,
not a tagged release or evidence of live installation.

## 2026-10-11

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
