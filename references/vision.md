# Vision and principles

Read this before changing Top Mode. Every change should move toward this picture
and keep these principles; when one conflicts with another, the earlier one wins.

## Goal

Help people who already use Codex or Claude Code get the most out of the
subscription they pay for: spend spare capacity on **their own priorities**,
without babysitting and **without losing control**.

## The user's journey

1. **Install once.** One step makes Top Mode available in Codex and Claude Code.
2. **Set up once, by conversation.** The agent looks at the user's workspace,
   proposes projects, priorities and a permission level, and the user approves.
   The setup stays private and is updated as things change.
3. **Get told when it's worth it.** A quiet periodic check speaks up only when
   there is something to use: weekly allowance about to renew with plenty left,
   saved resets about to expire, or an announced reset.
4. **Start with one sentence.** "Start Top Mode for 2 hours."
5. **Know what happened.** Every run ends with a short report: before and after,
   what is pending, and what it used.

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

- A task manager: Top Mode reads priorities from where the user already keeps them.
- Automatic model routing: the agent picks models within the host's options.
- A hosted service, cloud checker or anything that needs an extra account.
- Spending quota for its own sake: useful outcomes come first.

## Where we are

Done: plain-language docs, private setup that later sessions recover, quota
suggestion and token report from local logs, manual runs with deadlines and
reports, an experimental watch for announced Codex resets, and quality gates in
CI (Python 3.9+, lint, formatting, coverage floor, documentation links, macOS).

Next, in small pull requests:

1. **One-step install and a proactive check.** Install for Codex and Claude
   Code; one `check` command that combines quota, expiring resets and the
   announcement watch, and a recipe to run it daily with the agent's own
   scheduler.
2. **Guided setup.** The agent discovers projects and pending work from the
   workspace; three permission levels with optional detail; the profile points
   to where work lives instead of copying task lists.
