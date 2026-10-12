# Top Mode report (fictional example)

Everything below is invented to show the format. It is not real data.

## Waiting on you

- **Notes app:** approve the release? Recommended: yes; the fix is tested,
  reviewed and merged, and the notes session ships it once you approve.
- **Fitness tracker:** give the export task access to your account? Recommended:
  not yet; nothing else depends on it. Until then it stays blocked.

## What changed

**Notes app**
- Before: importing the same file twice duplicated every entry.
- After: imports are deduplicated; covered by two new tests, reviewed and merged.
- Why it matters: no more manual clean-up after each import.
- Pending: release. Next: you approve the release, then the notes session ships it.

**Personal website**
- Before: the contact form had no spam protection.
- After: a fix is ready in a pull request; tests pass. Not reviewed yet.
- Pending: review. Next: the review session checks it at the start of the next run.

**Fitness tracker** (attempted, not delivered)
- The data export task was blocked: it needs access to an account (`ask` in your
  setup). Nothing was changed. Next: you decide whether to grant access.

## The run

| | |
| --- | --- |
| Started | 2033-05-18 18:00 UTC, by your request ("Top Mode for 2 hours") |
| Deadline | 20:00 UTC |
| Stopped | 19:52 UTC, all ready work done (deadline not reached) |
| Closed | 19:55 UTC, after collecting checkpoints |
| Weekly quota | 38% used at 17:58 → 71% at 19:53 (Codex local logs). Includes anything else you ran meanwhile. Renews 2033-05-20 04:00 UTC. |
| Sessions | 3 started, 2 finished, 1 blocked (plus this coordinator) |

## Tokens (this machine, 18:00–19:53 UTC)

| Agent | Model | Effort | Responses | Total tokens |
| --- | --- | --- | ---: | ---: |
| codex | strong-model | high | 212 | 4,105,330 |
| codex | economical-model | medium | 64 | 612,904 |

Counted from local logs with `usage_report.py tokens`. Most input tokens are
cached context re-read on each response. Token counts are not your bill and do
not prove savings.

## Unknown

- Five-hour window: not reported by this host.
