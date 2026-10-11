# Codex Top Mode

Help an agent finish useful pending work during a bounded session, with quality
and verifiable progress ahead of quota consumption. Licensed under
[MIT](LICENSE).

## Give your agent one link

Share this README URL with an agent already working on your machine, or give
it the cloned/extracted folder:

> Read this guide and [the skill](SKILL.md). Prepare and explain my private
> configuration: projects and exclusions, priorities, each task's benefit and
> verifiable finish, current owners, permissions and duration. Use appropriate
> available models without reducing quality. Do not start until authorized.

The agent prepares the files; you do not need to edit JSON. The examples are
fictional and disabled. Then choose **manual top mode** for a stated duration,
or a **verified primary announcement** under your prior conditional permission.
Future news needs clearly future primary text, not an exact reset hour; unknown
hours stay unknown. Applied automatic or ambiguous news does not start work.

The agent observes native quota and the fixed deadline, stops new assignments
when weekly replenishment or the agreed stop is reached, and gathers bounded
worker checkpoints. Its [run report](references/profile-contract.md#run-report)
explains **before / after / pending / next step**, by project, with sourced time,
quota and execution metrics; unavailable data stays unknown. Publication,
review, merge and sensitive actions keep their permissions. See the
[changelog](CHANGELOG.md) for user-visible changes.

## Optional four-hour public watch

Ask the agent to test one local check, then schedule that same `--once` command
with **its supported scheduler**, initially every four hours. No additional
account, paid API, X login, Work, Page, dashboard or receiver is required.

The watch reads public X profile data and the publisher's official embed using
standard-library HTTP. It never executes page JavaScript. Author, original post
identity, publication day and primary text must match. For a primary post with a
verified quoted-post identity, the embed may append one anchored `t.co` link;
other additions or changed content remain unknown. The first enabled check fixes
the installation timestamp; existing posts do not trigger. If that first read
fails, the timestamp is preserved so later verified posts are not discarded. It outputs only newly verified public
posts needing interpretation, or one notice after eight hours of failed coverage.
Unchanged checks are quiet. The agent interprets only new posts, verifies upcoming
versus applied and mechanism from primary text, then checks permission, freshness,
ready work and native quota before using the capacity preflight.

The script makes **no model calls**. A scheduler that wakes an agent/model every
four hours still has that cost; an empty result should end quickly. A receipt
on stdout or in private state does **not** wake or resume an agent by itself.
Test the host's scheduling and notification hook before promising that behavior.
Without a supported scheduler/hook, the explicit alternative is a manual check.

## Real requirements and limits

- Python 3.11+; no third-party runtime dependencies. The watcher uses macOS/Linux
  file locking and refuses unsupported platforms rather than weakening one writer.
- Approved project access and private local configuration/state. Native quota
  observation, such as Codex `get_usage_limits`, is a separate host capability.
  Without it, only supervised work with an agreed deadline is available; reliable
  automatic weekly stopping cannot be claimed. Never read authentication stores
  or create an authentication client.
- A running, reachable machine and the scheduler/client capabilities actually
  tested. Closing or pausing the host interrupts observation. Check deadlines,
  permissions, ownership and fresh quota before resuming work.
- X's visible timeline is **partial discovery**, not a complete news feed. Failed
  reads, login walls, changed formats or doubtful author/time become unknown
  coverage. A successful known-post read does not prove continuous coverage.
  Third-party histories can discover links but cannot trigger work; incident feeds
  do not guarantee future promotions. No scraper daemon or universal executor is
  provided.

## Agent setup and local commands

Read [the profile/event contract](references/profile-contract.md). Prepare a
private `.local/` directory with owner-only access; adapt the disabled examples
there after human approval. Keep real files out of source control. Watch permission
is independent from permission to execute top mode.

```sh
python3 -B scripts/public_watch.py --once --config .local/watch.json --state .local/watch-state.json
python3 -B scripts/public_watch.py --status --config .local/watch.json --state .local/watch-state.json
python3 -B -m unittest discover -s scripts
```

`--once` reads when the configured interval has elapsed, allowing scheduler
jitter of one eighth of the interval, capped at 30 minutes. A four-hour schedule
therefore tolerates runs up to 30 minutes early regardless of their UTC phase;
`nextCheckAt` is the earliest eligible time after the last actual attempt. Repeated
or stale calls before that time make no request. Larger delays or clock errors
remain the scheduler's responsibility. No scheduler is created.
`--status` reads saved coverage without HTTP. Installation time is fixed before the first read;
successful reads seed the known IDs. Outputs
are `needs_interpretation`, `coverage_failure` or `coverage_recovered`; no output
means no new **verified visible** signal, not “there are no announcements”. State
keeps bounded IDs, a replay floor for evicted posts, and the latest 50 receipts.
Newly visible posts after installation can be received out of order while within
that retention horizon; older evicted posts cannot replay.
This is a discovery receipt, not the neutral activation event: the coordinator
must verify/classify it and remains the sole writer of its own work policy/state.

## Optional maintainer review

The [Claude workflow](.github/workflows/claude.yml) reviews maintenance PRs for
this repository. It is not a requirement for installing or using Top Mode.
The model reads frozen PR files; it cannot execute PR code, edit files or write
to GitHub. Trusted workflow code verifies and publishes its result.

A maintainer using this integration needs a personal Claude subscription
credential. Use Anthropic's [official token setup](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token),
then have the human owner enter, confirm and submit it directly in the repository's
**Settings → Secrets and variables → Actions** form, named
`CLAUDE_CODE_OAUTH_TOKEN`. Never put the value in a chat, issue, source file or
commit, and never extract an existing credential store. An agent must hand this
credential-entry step to the human.

Only the repository owner may dispatch or rerun it, from the default branch
(`main` here). First verify the PR is open, ready for review and non-draft, its
checks pass, and its head is the exact full 40-character SHA you intend to review.
Replace both placeholders below; leave the default economical runner unchanged:

```sh
gh workflow run .github/workflows/claude.yml --repo adpablos/codex-top-mode --ref main \
  -f pr_number=PR_NUMBER -f head_sha=FULL_HEAD_SHA
```

Use repository **Actions → Claude final review** to find that dispatch. Accept
a review only when its run succeeds and `github-actions[bot]` publishes a
**Claude final review** comment for the exact current head, base head and merge
base, with complete coverage and `Verdict: ready to merge`. The Actions run's
own head is the default-branch workflow revision, not the PR head. Check the
comment's frozen identity against the live PR; movement invalidates the verdict.
Merge remains a separate authorized action; the workflow never auto-merges.

For `changes required`, fix the material findings together and request closure
review of the new frozen identity. Do not run a parallel Cloud or `@claude`
review of the same candidate. Diagnose failed runs before retrying. A standard
runner recovery needs verified economy watchdog-timeout evidence and its
`fallback_run_id`; authentication, setup failure or cancellation does not qualify.
After ten completed published passes, continuation needs a diagnosed, explicit
per-pass human decision with an unused `extra_pass_authorization` reference.
Read the workflow's input and refusal rules rather than inventing authority.

## Contributing and security

Record user-visible package changes in the [changelog](CHANGELOG.md). Keep real
run reports and metrics in private storage.

Keep changes small; run the tests above with synthetic fixtures and no real
model/account calls. [GitHub Actions](.github/workflows/tests.yml) runs the same
offline suite on pull requests and pushes to `main`, with Python 3.13, pinned
official actions and read-only permissions. Verify the **Offline tests** run
and its test count; reproduce locally with
`python3.13 -B -m unittest discover -s scripts -v`. No runtime dependency
installation, X/model calls or repository secrets are required by the tests.
Preserve authorization, fixed deadlines, deduplication,
coverage honesty, private storage and legacy observer behavior. Use supported
public HTTP only. Do not include keys, cookies, account IDs, real profiles or
private conversations in fixtures, issues or patches. Do not publish sensitive
reports as issues: use a maintainer's private contact if available, otherwise
request one without disclosing the material. No private reporting endpoint is
claimed before publication.
