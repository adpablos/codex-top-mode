# Vision and principles

Read this before changing Quota Coach. Every change should move toward this picture
and keep these principles; when one conflicts with another, the earlier one wins.

## Goal

Help people who already use Codex or Claude Code get the most out of the
subscription they pay for: spend spare capacity on **their own priorities**,
without babysitting and **without losing control**. Measuring quota is not our
job: [CodexBar](https://codexbar.app) does it well, and we read it when it is
there. Ours is what comes after: whether it is worth it, the work itself, the
report and whether the plan fits.

## The user's journey

1. **Install once.** One step makes Quota Coach available in Codex and Claude Code.
2. **Set up once, by conversation.** The agent looks at the user's workspace,
   proposes projects, priorities and a permission level, and the user approves.
   The setup stays private and is updated as things change.
3. **Get told when it's worth it.** A quiet periodic check speaks up only when
   there is something to use: weekly allowance about to renew with plenty left,
   or saved resets about to expire.
4. **Start with one sentence.** "Start Top Mode for 2 hours."
5. **Know what happened.** Every run ends with a short report: before and after,
   what is pending, and what it used.
6. **Understand your Codex plan.** Compare its observed weekly use, including
   Top Mode, with other plans and coming changes; decide which work to keep
   before treating that comparison as a reason to change tiers.

## Principles

1. **The user stays in control.** Nothing runs without their approval. Every run
   has a deadline nothing can extend. Saved resets are never spent for them. They
   can ask for status at any time and always get a report.
2. **Simple for the user.** Plain words, short phrases, sensible defaults
   (three permission levels before any fine-grained setting). The agent asks
   only what it cannot find out by itself.
3. **Simple code.** Python standard library only, few scripts, no service,
   account client, daemon or dashboard. Prefer removing or merging over adding.
   Every new piece must serve a step of the journey above.
4. **Honest.** Say what was checked and what is unknown. Never guess quota,
   tokens, coverage or success.
5. **Local and private.** Everything runs on the user's machine. Setup, state
   and reports stay outside Git and never leave it.
6. **Quality.** Behaviour is covered by fast offline tests; CI keeps lint,
   formatting, coverage and documentation links honest.

## Not goals

- A task manager: Quota Coach reads priorities from where the user already keeps them.
- Automatic model routing: the agent picks models within the host's options.
- A hosted service, cloud checker or anything that needs an extra account.
- A quota meter, usage dashboard or cost history: CodexBar and ccusage do that.
- Watching for announced resets: public trackers do that.
- Spending quota for its own sake: useful outcomes come first.

## Where we are

Done: plain-language docs, private setup that later sessions recover, quota
suggestion and token report from local logs, manual runs with deadlines and
reports, quality gates in CI (Python 3.9+, lint, formatting, coverage floor,
documentation links, macOS), one-step install for Codex and Claude Code, a
quiet `check` command to schedule with the agent's own scheduler, quota from
CodexBar for Codex and Claude Code (Codex's local logs without it), a verdict
on whether the Codex plan has been enough, from its weekly history, compared
with the other Codex plans, a guided setup (the agent discovers projects and
where their work lives, and the user picks one of three permission levels), and
a private journal of each run that answers "status" and drafts the report.

Current limits: plan comparison covers Codex only, and account readings cannot
separate Top Mode from ordinary use. Reliable attribution and a suitable Claude
history source are prerequisites for broader advice; collecting more readings
alone does not solve attribution.
