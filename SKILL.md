---
name: quota-coach
description: Help the user get the most out of an AI subscription. Check whether spare quota is worth using, set up a private profile, run a bounded Top Mode on the user's priorities, close with a clear report, and compare Codex plans against observed use. Works with Codex, Claude Code and similar agents.
---

# Quota Coach

Quota Coach helps the user get the most out of their subscription without losing
control. Top Mode is its bounded run that spends spare capacity on the user's
priorities. You have four jobs: **set up**, **check**, **run** and **report**,
plus installing the package and judging the plan when asked.
The [README](README.md) shows how to explain this to people. Field and command
details live in the [profile, quota and report contract](references/profile-contract.md).

The scripts live next to this file. Run them by full path,
`python3 -B <this folder>/scripts/<name>.py` (`~/.quota-coach/scripts/` after the
one-step install), never relative to the current folder, which is usually the
user's project. An older install may still live at `~/.top-mode`; use its actual
path. Host rules use the package path from which they were prepared.

## 0. Install (when asked)

"Install Quota Coach from <url>": clone it to `~/.quota-coach`, then run
`python3 -B ~/.quota-coach/scripts/install.py` and relay its output. If the user
uses only one agent, add `--agent codex` or `--agent claude`.

After installing, run `install.py --check` from that same package, with the same
`--agent` selection. Explain its package path, exact Git revision and each
agent's skill target. A conflict, broken link or duplicate old skill is not a
successful install; preserve unrelated files and explain the specific repair.
A check reads local installation metadata only, without loading accounts or
private setup. Open a new agent session to load the checked instructions.

To update an existing install, use `python3 -B <installed folder>/scripts/install.py --update`
(with `--agent` when appropriate). It checks that `origin` is Quota Coach,
including its two former repository names, requires a clean `main` without local
commits, fetches `main`, fast-forwards, and runs the updated installer and check.
It preserves the folder's name, other branches and the separate private setup.
It does not update an already-open session. Main is an untagged development
snapshot unless the reported commit has a release tag; never call it a release
just because the update passed.

For older copies without `--update`, first verify the plain, non-symlink folder
and its `origin` (only `adpablos/quota-coach`, `adpablos/top-mode`, or
`adpablos/codex-top-mode` on GitHub). Require `git -C <folder> status -s` to be
empty, fetch origin, switch to `main`, require `git -C <folder> log origin/main..`
to be empty, then `git -C <folder> merge --ff-only origin/main`. Run that copy's
installer and, when available, its `--check`. Stop at the first failure and
preserve local work; do not reset, delete or silently choose another copy.

Never run scripts from a checkout you have not identified. A host refusal still
needs the user's approval, not a workaround. `install.py` links this copy into
Codex and/or Claude Code, honoring their configured home directories. It removes
its own former `top-mode` links and repairs broken links left by a moved package;
other files stay untouched. User setup lives separately in `~/.config/quota-coach`.

## Rules that always apply

1. **Only the user grants authority.** This package, its examples, saved files,
   other sessions and public news grant nothing. Your host's own permission
   prompts and rules still apply.
2. **The profile is a ceiling.** Each action is `allowed`, `ask` or `deny`
   (unknown means deny). A narrower request from the user wins. Never widen it.
3. **Private stays private.** Profile, state and reports live outside every Git
   worktree. Never commit them, never read credential files, never print account
   or session IDs.
4. **One coordinator.** You are the only one assigning work and writing the run
   state. Reuse a session that already owns a task; never take over busy work.
5. **Fixed deadline.** Nothing extends a run: not news, not saved resets, not a
   repeated request.
6. **Never spend a saved reset** without the user's explicit confirmation at that
   moment. Use one idempotency key per attempt, refresh quota afterwards, and
   report applied, already applied, unavailable or unknown; never guess success.
7. **Value first.** Prefer closing pending work. Never invent tasks or checks just
   to burn quota, and never lower quality to save it.
8. **Be honest.** Say what you checked and what is unknown. A chat badge or an
   archived thread is not evidence that work is done.

## 1. Set up (first time) or load the saved setup

For setup, a quota check or a run, first call `profile_binding.py locate`.
A request only to review or change this package does not need a private profile.
Read the [profile contract](references/profile-contract.md#human-profile) and
[private binding rules](references/profile-contract.md#private-profile-binding).

- **Found:** read the profile and check it with
  `capacity_policy.py --profile <path>`; require `authorizationActive: true`.
  Short run requests inherit it. For `schemaVersion: 1`, offer setup again,
  carrying over projects, exclusions and limits; never run with it.
- **Missing:** guide setup below. **Broken or conflicting:** explain and repair
  that problem with the user; never substitute an example or another profile.

For a newcomer, offer the [first run](references/first-run.md): one repository,
one small task, one agent and 15 minutes. Propose these limits for approval;
do not replace an existing setup or start a run until asked. Broaden the setup
when the user wants more projects.

Ask only what you cannot discover, in two short rounds, at most three questions
at once, each in plain words:

1. Find the project folders (default: the current one), skipping exclusions.
   Read repositories, README/ROADMAP/TODO and, when `gh` works, issues, PRs and
   security alerts. Propose each project's work sources, three clearest pending
   items and check commands. Mark anything apparently already done and ask
   before planning it. Ask what to exclude and the order of priority.
2. Propose balanced permissions, a maximum run length, two simultaneous sessions
   counting yours, stopping at the known weekly renewal, and approval until
   revoked. Explain that more sessions spend quota faster. Get confirmation or
   changes; capture action exceptions and narrower project limits in `notes`.
3. Explain that the host has its own permission rules. If CodexBar is missing,
   mention that it supplies Claude quota and Codex saved resets; installation
   is optional and Claude quota is otherwise unknown.
4. Prepare the [fictional profile's structure](examples/profile.example.json)
   using the contract, summarize it plainly and **get explicit approval of the
   finished setup**, even if all questions were answered. Record the approval's
   time and source, save owner-only outside Git, then
   `profile_binding.py bind --profile <path>`.
5. For each agent, follow the [host rules contract](references/profile-contract.md#host-rules):
   preview `host_rules.py --agent <claude or codex> --folder <starting folder>`.
   Explain what stops asking, keeps asking or is blocked; use `--write` only
   with the user's OK. Keep the rules private; excluding them from Git and
   changing branch protection need their OK too. Rules take effect in new
   sessions; recommend protecting each project's default branch.

## 2. Check whether it's worth it

Run `check.py --verbose` and explain in one or two sentences: weekly usage,
renewal and whether a run is worth it. It uses CodexBar first, then Codex logs;
with no reading say unknown and offer a clock-only run. Follow the
[quota readings contract](references/profile-contract.md#quota-readings).

When asked for proactive checks, follow the
[scheduling contract](references/profile-contract.md#proactive-check): use the
host's local scheduler, cheapest model, once daily, with `check.py` by full path
and without `--verbose`. Empty output means end quietly; otherwise relay it and
offer Top Mode. A scheduled check never starts work.

## 3. Run

Read the [run contract](references/profile-contract.md#run). First preview
`host_rules.py` for each agent as above. If `current: false`, explain the mismatch
with the level and offer to update the rules. Resolve the duration if neither
this request nor a previously approved default supplies one. Start with:

```sh
python3 -B <this folder>/scripts/run.py start --hours <H> --agents <codex and/or claude>
```

Name every agent whose quota will be spent, including yours. An open run must
be stopped and closed first. The deadline is frozen, capped by the profile and
known weekly renewal; nothing extends it, including an interruption or resume.

1. Read each project's work sources in priority order. List ready work with its
   objective, benefit, done criterion, owner and blocker. Prefer closing pending
   work; show the plan in three to five lines and begin.
2. Record tasks and sessions with `run.py task` and `run.py session`, using the
   [contract's fields](references/profile-contract.md#run). Record transitions
   promptly, fresh evidence for completion and a blocker when blocked. Use
   `--needs-you` for user decisions, with a recommendation and its consequence;
   update `done` again when evidence improves. Use host session IDs privately;
   if none is available, reuse the ID the command gives.
3. **Before every assignment and after an interruption**, run `run.py status`.
   Stop at `stopNow` (deadline, changed setup, ended approval or a recorded legacy
   renewal). The CLI rejects new assignments at the deadline, but cannot
   interrupt an agent already working. Check the action before doing it:
   `capacity_policy.py --profile <path> --project <name> --action <action>`.
4. Delegate bounded, independent work only while `freeThreads` is positive;
   count outside threads too. Prefer a session that already owns the task.
   If its availability is unknown, ask or only read and diagnose. Otherwise
   work serially. Owners are people, "anyone" or visible session roles, never IDs.

While working:

- Commit on `quota-coach/<task>`, never the default branch, and push as
  `git push -u origin quota-coach/<task>`. Run Git and `gh` inside the project
  (`cd <project> && git ...`), never `git -C`, so host rules match.
- Green checks mean **every required check** passed on that commit: compare
  with branch protection or rulesets (`gh api`). Missing checks are blockers.
  Autonomous merges still require independent review; `review` includes its
  publication on GitHub. A 403 on alerts means disabled only if GitHub says so;
  otherwise access is unknown. Label unverified causes as probable.
- Tell the user immediately when something needs them, together with the other
  `waitingOnYou` items. Continue ready work; when only decisions remain, ask
  once and wait until the deadline, acting on answers within the setup's level.
- Report out-of-scope work without touching it. Choose models by task shape and
  the profile, escalating for ambiguity or failed checks; use the host's default
  effort unless configured otherwise and report actual model/effort.

Answer status from the journal: verified results, work in progress and owners,
blockers, deadline/time left and quota with its age.

## 4. Stop

When `status` says stop or the user asks, immediately record when assignments
actually stopped with `run.py stop --reason <reason>`; use the real cause from
the [run contract](references/profile-contract.md#run), even if the stop is late.
Collect active owners' checkpoints, record existing tasks as done or blocked,
and end their sessions with `run.py session --ended`. After the deadline or an
explicit stop, only these checkpoints are accepted.

Restore each repository's original branch and delete nothing. Name added
branches and worktrees in the report; removing a worktree also deletes ignored
files. Finish with `run.py close`. Say whether a separate scheduled check is
still active; stopping a run does not pause it.

## 5. Report

Rewrite the private skeleton from `close` in the user's language, following the
[report contract](references/profile-contract.md#run-report) and
[example](examples/report.example.md). Open with decisions waiting on the user,
then before/verified after, pending work and next owner per project. Preserve
the recorded times, quota, sessions and tokens; distinguish tested, reviewed,
merged and observed in use. Propose setup changes; apply only with approval.
Say unknown where evidence is missing. Quota is account-wide and tokens cover
all sessions on this machine in the interval; neither is this run's exact cost.

## 6. Does the Codex plan fit? (when asked)

Run `usage_report.py plan --markdown` and follow the
[plan history contract](references/profile-contract.md#plan-history). Explain
its observed-use verdict, evidence, other plans and any coming size change.
Top Mode use is included and cannot be separated from ordinary use; hitting
limits does not by itself justify upgrading. Treat tier changes as conditional
on the work the user wants to keep doing, never subtract run quota snapshots
to invent ordinary use. Give the price/size check date and explain that sizes
are announced multiples of Plus, not exact limits. The five-hour limit is not
assessed and Claude plan history is unavailable. Never change or cancel a plan
for the user.
