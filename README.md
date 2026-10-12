# Quota Coach

[![Checks](https://github.com/adpablos/quota-coach/actions/workflows/tests.yml/badge.svg)](https://github.com/adpablos/quota-coach/actions/workflows/tests.yml)

**Use the AI subscription you already pay for, on purpose and without losing track.**

Coding-agent subscriptions come with weekly limits. Whatever you don't use before
the limit renews is gone, and the plan you pay for may be too small or bigger
than you need. Quota Coach is a skill for your agent (Codex, Claude Code or any
agent that can read files and run Python) that helps you get the most out of it:

- **It tells you when it's worth it.** Your weekly allowance renews soon and a
  lot is still unused, or saved resets are about to expire.
- **Top Mode works on your priorities, with your rules.** When you say so, it
  spends the spare capacity on your projects. You decide what to leave out, and
  what the agent may do alone or must ask first.
- **It stops on time.** Every Top Mode run has a deadline that nothing can extend.
- **It tells you what happened.** Each run ends with a short report: what changed,
  what is pending, and what it used (quota before and after, tokens per model).
- **It tells you whether your plan fits.** From your Codex quota history: enough,
  short, or a cheaper plan would do, and what a coming change to your plan means.

Downloading it starts nothing and changes no settings. It is a set of instructions
plus small Python scripts with no dependencies. [MIT license](LICENSE).

## Get started

**1. Install.** Ask your agent (Codex or Claude Code):

```text
Install Quota Coach from https://github.com/adpablos/quota-coach
```

It runs two commands you can also run yourself:

```sh
git clone https://github.com/adpablos/quota-coach ~/.quota-coach &&
  python3 ~/.quota-coach/scripts/install.py
```

This makes Quota Coach available as a skill in every new Codex and Claude Code
session. Your agent may ask you to approve running the install script; that is
expected. Update with `git -C ~/.quota-coach pull`; undo with
`python3 ~/.quota-coach/scripts/install.py --remove`. Installed it as Top Mode?
Ask your agent to update Top Mode; your setup and folder stay as they are.

**2. Set up, once.** In a new session, say *"Help me set up Quota Coach."* The
agent looks at the folders you point it to, proposes your projects and where
their pending work lives (issues, pull requests, a roadmap file), and asks only
what it can't find out: what to leave out, the order, a permission level, a time
limit, how many sessions may work at once and how long your approval lasts
(until you revoke it, by default). It shows you the setup in plain words and
saves it, after your approval, in a private file outside any Git repository. You
never need to edit JSON.

**3. Get told when it's worth it (optional).** Say *"Run the Quota Coach check
once a day with your cheapest model and only tell me when there is
something."* The agent schedules a quiet check with its own scheduler. It speaks
up only when there is spare capacity to use.

**4. Use it.** From then on, short sentences are enough:

| You say | What happens |
| --- | --- |
| "Is it worth running Top Mode now?" | It checks your quota and says yes, no or unknown, and why. |
| "Start Top Mode for 2 hours." | It reads your projects' pending work, shows you its plan in a few lines and gets going. |
| "Status." | What is done and checked, what is in progress, blockers, time left. |
| "Stop Top Mode." | No new work; running tasks save a checkpoint; you get the report. |
| "Explain the report." | Before, after, pending and next step, per project. |
| "Is my plan enough?" | From your Codex quota history: enough, short, enough only thanks to resets, or a cheaper plan would do; how the other plans compare and any coming change to yours. |

## When is it worth it?

| Signal | Codex | Claude Code |
| --- | --- | --- |
| Weekly allowance renews soon and plenty is unused | Yes, from Codex's local logs | Yes, if you let the agent save your status line ([how](references/profile-contract.md#quota-readings)); otherwise it asks you |
| Saved resets are about to expire | Only from Codex's own usage payload, saved and passed to the check ([how](references/profile-contract.md#proactive-check)); local logs don't list them | Not applicable |
| You simply want to push work forward | Yes | Yes |

The check only suggests. Top Mode only starts when you say so. For announced
Codex resets, follow a public tracker such as
[Codex Resets](https://mcpservers.org/remote-mcp-servers/codex-resets).

## You stay in control

- **Nothing runs without your approval.** Examples and news never count as permission.
- **You pick a permission level,** and can change single actions on top of it:

  | Level | Does alone | Asks you first | Never |
  | --- | --- | --- | --- |
  | Careful | read, edit, run tests, commit on a branch | open a pull request, request a review, merge, install, use your accounts | money, deleting things |
  | **Balanced** (default) | the above, plus open a pull request and request a review | merge, install, use your accounts | money, deleting things |
  | Autonomous | the above, plus merge once an independent review and the checks pass | install, use your accounts | money, deleting things |

  On Claude Code and Codex, the setup can write your level into the agent's own
  permission rules, with your OK, so it stops asking for what you allowed. On
  other agents, their own permission settings still apply on top.
- **Fixed deadline.** It stops at the time limit, if you revoke permission, or
  (when the agent can see your quota) when your weekly allowance renews.
- **One coordinator.** One conversation keeps track of everything. It reuses
  sessions that already own a task instead of piling up new ones.
- **Saved resets are never spent for you.** Each one needs your confirmation.
- **Your setup stays private.** It lives outside Git; updating this package keeps it.

## What a report looks like

> **Notes app.** Before: the import could duplicate entries. After: fixed, tested
> and merged. Pending: release (needs your OK). Next: you approve the release.
>
> **Run:** 1 h 52 min of 2 h, stopped at the deadline. Weekly quota 38% → 71%.
> Tokens: 4.1 M on the strong model, 0.6 M on the cheap one, across 3 sessions.

Full example: [examples/report.example.md](examples/report.example.md).

## What's inside

| File | What it is for |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Entry point for agents. |
| [SKILL.md](SKILL.md) | How the agent sets up, runs, stops and reports. |
| [references/profile-contract.md](references/profile-contract.md) | The setup file, quota sources and report rules. |
| [scripts/install.py](scripts/install.py) | Makes Quota Coach available in Codex and Claude Code. |
| [scripts/check.py](scripts/check.py) | The quiet check: speaks only when there is capacity worth using. |
| [scripts/usage_report.py](scripts/usage_report.py) | Quota details, tokens per model and plan history from local logs. |
| [scripts/plan_fit.py](scripts/plan_fit.py) | Rebuilds weekly windows from quota readings, judges the plan and compares the others. |
| [references/plans.json](references/plans.json) | Codex plan prices and sizes, with sources and the date they were checked. |
| [scripts/profile_binding.py](scripts/profile_binding.py) | Remembers where your private setup lives. |
| [scripts/run.py](scripts/run.py) | Keeps a private journal of each run: deadline, quota, tasks and sessions. Answers "status" and drafts the report. |
| [scripts/usage_monitor.py](scripts/usage_monitor.py) | Watches Codex quota during a run and decides when to stop. |
| [scripts/capacity_policy.py](scripts/capacity_policy.py) | Checks your setup: is it valid, and what an action needs. |
| [examples/](examples/) | Fictional setup and report examples. |

## Limits

- Needs Python 3.9 or newer (the one that comes with macOS works) and an agent
  that can run commands on your machine.
  Everything runs locally; there is no service, account or dashboard.
- The agent only works while your machine and agent are running. A closed laptop
  doesn't watch anything.
- Token counts come from local logs on this machine. Work done elsewhere isn't counted.
- Quota is shared by everything on your account, so before/after numbers include
  any other work you did meanwhile. The report says so.
- Plan advice covers Codex only for now and still counts Top Mode runs as your
  own use. Providers publish no exact limits: plans are compared
  by the multiples of Plus that OpenAI has announced, never in tokens. Prices
  and sizes change; the file says when they were checked.
- These are instructions for an agent, not a sandbox. Your agent's own permission
  settings still apply, and its rules match a command's words, not what it does:
  protecting your main branch on GitHub is the real guard.

Contributing: start with the [vision and principles](references/vision.md), then
the [maintenance guide](references/maintaining.md) and the [changelog](CHANGELOG.md).
