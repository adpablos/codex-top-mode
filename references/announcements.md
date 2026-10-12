# Reset announcements (optional, Codex)

Top Mode works without this. It is an optional, experimental watch for one kind
of news: OpenAI staff sometimes announce on X that Codex usage will be reset.
An announcement that arrives before the reset is the one signal that lets you
use what is left before it is restored anyway.

**The watch only tells you.** It never starts work. When news arrives, the agent
reads it, tells you what it says, and you decide whether to start Top Mode.

## How it works

[`public_watch.py`](../scripts/public_watch.py) reads the public posts of the X
accounts you approve and reports only **new** posts. It makes no model calls and
stays silent when nothing changed. [`check.py`](../scripts/check.py) runs it
whenever `~/.codex-top-mode/watch.json` exists and turns each result into one line:

- `New announcement to read: <post URL> (<start of the text>)`
- `Could not read <account> for a while; announcements may be missed.`
- `Reading <account> works again.`

X often blocks anonymous reads, so coverage is partial. No line means no new
post was seen, not that nothing was announced.

## Set up

With the user's OK, copy the [watch example](../examples/watch.example.json) to
`~/.codex-top-mode/watch.json` with owner-only access (keep an existing one and
its `watch-state.json`). List the approved accounts in `publishers` as
`https://x.com/<name>` and set `enabled` to `true`. Then schedule the
[proactive check](profile-contract.md#proactive-check) every 4 hours. Agreeing
to watch an account is not permission to run Top Mode.

## When a new announcement arrives

1. **Read the post itself**, at the URL in the line (see
   [reading a post](#reading-a-post)). A snippet, a forecast or someone else's
   summary is not the post.
2. **Tell the user** in one or two sentences: who posted, when, and whether it
   announces a reset that is coming (and when, if it says), one that has
   already happened, or something unclear. Say what you could not verify.
3. **Offer to start Top Mode**, and start only when the user says so, with the
   usual deadline and permissions. News is never permission and never extends
   a run that is already going.

A reset that is coming is the useful case: what is left now will be restored
anyway. If the post says the reset already happened, check the quota first;
there is usually nothing to rush.

## Reading a post

For a known post URL, use the host's tools to read the public page. On X, a
public alternative owned by the publisher is the official oEmbed endpoint,
`https://publish.twitter.com/oembed?url=<URL-encoded post URL>&omit_script=true`.
Read the returned text without running scripts. Use only public,
unauthenticated reads: no cookies and no account client. A failed read (often
a 403) means unknown, not "nothing happened".

## Watch details

Run from the package root:

```sh
python3 -B scripts/public_watch.py --once \
  --config "$HOME/.codex-top-mode/watch.json" --state "$HOME/.codex-top-mode/watch-state.json"
python3 -B scripts/public_watch.py --status \
  --config "$HOME/.codex-top-mode/watch.json" --state "$HOME/.codex-top-mode/watch-state.json"
```

- `--once` reads only when `intervalHours` has passed, tolerating scheduler
  jitter of one eighth of the interval (at most 30 minutes); earlier calls make
  no request. `--status` shows saved coverage without any request.
- The first enabled check fixes the installation time; posts from before it
  never trigger. If that first read fails, the time is kept, so later posts are
  not lost.
- A post counts only when its author, identity, publication day and text match
  between the profile page and the official embed. For a post that quotes
  another, the embed may add one `t.co` link; any other difference stays unknown.
- After `failureNoticeHours` of failed reads it reports one coverage failure,
  and one recovery when reads work again.
- State keeps bounded post IDs, a replay floor and the latest 50 results, so each
  post is reported once. Posts can arrive out of order within that horizon;
  older evicted posts cannot replay.
- It reads public X pages with the standard library and never runs page
  JavaScript. Nothing here installs a scheduler, daemon or feed. Every scheduled
  run wakes a model even when the watch is silent, so use the cheapest one.
