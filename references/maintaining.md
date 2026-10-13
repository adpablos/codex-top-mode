# Maintaining Quota Coach

This guide is for changing the package. To use it for your own work, start
with the [README](../README.md) and [agent entry point](../AGENTS.md).

Every change should fit the [vision and principles](vision.md).
Keep changes focused and preserve the [skill](../SKILL.md) and
[profile, quota and report contract](profile-contract.md) as the operating
sources.
Keep review, merge, release and deployment authority separate.

## Reviews

Every pull request gets an independent review before it merges, by an agent
other than the one that wrote it (for example `@codex review` on a change
Claude made). A review covers the commit it names: every later push needs a
review of what it added, and the PR merges only when the review covers its
current head and CI is green on it. Merging stays the owner's call.

## Contributing and security

### Installation and pilot checks

Keep installation diagnostics in `scripts/install.py`. Its `--check` is local
and read-only; `--update` fetches only the recognized repository's `main`,
refuses dirty or locally committed checkouts and reruns the updated installer.
Do not add another updater or version registry. Git revisions identify snapshots;
an exact release tag identifies a published version when one exists.

The offline suite includes temporary-repository update tests and a first-run
check through installed skill links, from a different working folder and across
separate processes. It covers private setup recovery, unknown quota, a task,
stop, completion checkpoints, report, and uninstall without losing private
state. Deadline enforcement is exercised with a controlled clock. These checks
use synthetic data and no provider calls; they do not prove host permission
prompts, model behavior or account integrations work in a live session.

Use the [first-run guide](first-run.md) for a 3–5-person pilot. Prepare a reviewed
candidate and record its exact commit; invitations, shared feedback and release
publication require the appropriate human authorization. Keep observations
private and bring only sanitized, reproducible problems into the repository.

Before an authorized release, require the checks on the exact commit, a clean
independent review and a completed manual first run in each supported agent.
Record known limits in the release notes, align the version in `pyproject.toml`,
and tag that same commit. Verify that installing and updating reach the
documented revision. Do not label a development snapshot stable based on CI
alone. Start with GitHub distribution; another package channel should solve a
measured installation problem from the pilot.

### Contributor checks

Record user-visible package changes in the [changelog](../CHANGELOG.md). Keep real
run reports and metrics in private storage.

Keep changes small. From the package root, run the same checks as CI. They are
offline, use synthetic fixtures and make no model or account calls:

```sh
python3 -B -m unittest discover -s scripts      # tests, including docs links
ruff check scripts && ruff format --check scripts
python3 -m coverage run -m unittest discover -s scripts && python3 -m coverage report
zizmor --offline .github                        # workflow security audit
```

The runtime has no dependencies and supports Python 3.9+ (the version macOS
ships). `ruff` and `coverage` are only for contributors; their settings live in
[pyproject.toml](../pyproject.toml). [GitHub Actions](../.github/workflows/tests.yml)
runs lint, format and a workflow audit, the tests with an 85% coverage floor on
Python 3.13, and the tests on macOS's own Python (3.9; the job fails if the
runner ships another version), with pinned actions and read-only permissions. Its `all checks` job fails when any of them fails; it is
the one check to require before merging. Dependabot proposes action updates
after a 7-day cooldown.
Preserve authorization, fixed deadlines, deduplication,
coverage honesty and private storage. Do not include keys, cookies, account IDs, real profiles or
private conversations in fixtures, issues or patches. Do not publish sensitive
reports as issues: use a maintainer's private contact if available, otherwise
request one without disclosing the material. No private reporting endpoint is
claimed before publication.
