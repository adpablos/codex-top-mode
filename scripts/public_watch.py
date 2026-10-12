"""One-shot anonymous public-news discovery. Never authorize or execute work."""

import argparse
import copy
import hashlib
import html
import http.client
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from usage_monitor import epoch, number, write_private

MAX_BYTES = 2_000_000
ASSIGNMENT = re.compile(r"\$R\[(\d+)\]=")
ENTRY = re.compile(
    r'\$R\[\d+\]=(?=\{content:\$R\[\d+\]=\{__typename:"TimelineTimelineItem")'
)


class SourceError(ValueError):
    pass


def publisher(value):
    if not isinstance(value, str):
        raise SourceError("Publisher URL required")
    url = urllib.parse.urlsplit(value)
    if (
        url.scheme != "https"
        or url.netloc.lower() != "x.com"
        or url.query
        or url.fragment
        or not re.fullmatch(r"/[A-Za-z0-9_]{1,15}/?", url.path)
    ):
        raise SourceError("Publishers must be canonical public X profile URLs")
    return "https://x.com/" + url.path.strip("/").lower()


class LiteralReader:
    """Read a narrow literal/reference subset of X's public SSR data, never JS."""

    def __init__(self, source):
        self.source = source
        self.positions = {}
        for match in ASSIGNMENT.finditer(source):
            self.positions.setdefault(match[1], match.end())
        self.references = {}
        self.resolving = set()
        self.nodes = 0

    def value(self, pos, depth=0):
        self.nodes += 1
        if depth > 60 or self.nodes > 50000:
            raise SourceError("Public data exceeds parser bounds")
        s = self.source
        while pos < len(s) and s[pos].isspace():
            pos += 1
        reference = re.match(r"\$R\[(\d+)\]", s[pos:])
        if reference:
            key = reference[1]
            pos += reference.end()
            if s[pos : pos + 1] == "=":
                value, end = self.value(pos + 1, depth + 1)
                self.references[key] = value
                return value, end
            if key not in self.references:
                if key not in self.positions or key in self.resolving:
                    raise SourceError("Unresolved public data reference")
                self.resolving.add(key)
                self.references[key], _ = self.value(self.positions[key], depth + 1)
                self.resolving.remove(key)
            return self.references[key], pos
        if pos >= len(s):
            raise SourceError("Truncated public data")
        if s[pos] == '"':
            try:
                value, length = json.JSONDecoder().raw_decode(s[pos:])
            except ValueError as error:
                raise SourceError("Unsupported public string") from error
            return value, pos + length
        if s[pos] in "{[":
            object_ = s[pos] == "{"
            result = {} if object_ else []
            closing = "}" if object_ else "]"
            pos += 1
            while True:
                while pos < len(s) and s[pos].isspace():
                    pos += 1
                if s[pos : pos + 1] == closing:
                    return result, pos + 1
                if object_:
                    if s[pos : pos + 1] == '"':
                        key, pos = self.value(pos, depth + 1)
                    else:
                        key_match = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", s[pos:])
                        if not key_match:
                            raise SourceError("Unsupported public object key")
                        key, pos = key_match[0], pos + key_match.end()
                    if s[pos : pos + 1] != ":" or key in result:
                        raise SourceError("Ambiguous public object")
                    value, pos = self.value(pos + 1, depth + 1)
                    result[key] = value
                else:
                    value, pos = self.value(pos, depth + 1)
                    result.append(value)
                if s[pos : pos + 1] == closing:
                    return result, pos + 1
                if s[pos : pos + 1] != ",":
                    raise SourceError("Unsupported public expression")
                pos += 1
        for token, value in (("!0", True), ("!1", False), ("null", None)):
            if s.startswith(token, pos):
                return value, pos + len(token)
        number = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", s[pos:])
        if number:
            return json.loads(number[0]), pos + number.end()
        raise SourceError("Unsupported public expression")


def profile_posts(source, approved_publisher, now):
    if len(source.encode()) > MAX_BYTES:
        raise SourceError("Public page too large")
    reader = LiteralReader(source)
    posts = {}
    identities = {}
    entries = list(ENTRY.finditer(source))
    if not entries:
        raise SourceError("No supported public timeline; coverage unknown")
    for match in entries:
        entry, _ = reader.value(match.start())
        try:
            identity = re.fullmatch(r"tweet-(\d{10,25})", entry["entry_id"])[1]
            result = entry["content"]["content"]["tweet_results"]["result"]
            if result.get("__typename") == "TweetWithVisibilityResults":
                result = result["tweet"]
            author = result["core"]["user_results"]["result"]["core"]["screen_name"]
            created = result["details"]["created_at_ms"]
            text = result["details"]["full_text"]
            actual_author = publisher("https://x.com/" + author)
            if (
                result["rest_id"] != identity
                or type(created) is not int
                or not 0 < created / 1000 <= now
                or not isinstance(text, str)
                or not text.strip()
                or len(text) > 10000
            ):
                raise SourceError("Public post author, identity or time is doubtful")
            post = {
                "sourceUrl": actual_author + "/status/" + identity,
                "author": actual_author,
                "publishedAt": created / 1000,
                "text": text,
            }
            quoted = result.get("quoted_tweet_results")
            if quoted:
                quoted_result = quoted["result"]
                if quoted_result.get("__typename") == "TweetWithVisibilityResults":
                    quoted_result = quoted_result["tweet"]
                quoted_id = quoted["rest_id"]
                if (
                    not isinstance(quoted_id, str)
                    or not re.fullmatch(r"\d{10,25}", quoted_id)
                    or quoted_result["rest_id"] != quoted_id
                    or quoted_id == identity
                ):
                    raise SourceError("Public quoted post identity is doubtful")
                post["_quotedPostId"] = quoted_id
            if identity in identities and identities[identity] != post:
                raise SourceError("Conflicting public post identity")
            identities[identity] = post
            if actual_author == approved_publisher:
                posts[identity] = post
        except (KeyError, TypeError, IndexError, AttributeError) as error:
            raise SourceError("Public timeline format changed") from error
    discovered = set(re.findall(r'entry_id:"tweet-(\d+)"', source))
    if discovered != set(identities):
        raise SourceError("Unrecognized public timeline entries")
    return sorted(
        posts.values(), key=lambda p: (p["publishedAt"], p["sourceUrl"]), reverse=True
    )


class EmbedReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.paragraphs = []
        self.paragraph_links = []
        self.current = None
        self.current_links = None
        self.anchor = None
        self.dated_links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            self.links.append(href)
            self.anchor = {"href": href, "text": []}
        if tag == "p" and self.current is None:
            self.current = []
            self.current_links = []

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["text"].append(data)
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            link = (self.anchor["href"], "".join(self.anchor["text"]))
            self.dated_links.append(link)
            if self.current_links is not None:
                self.current_links.append(link)
            self.anchor = None
        if tag == "p" and self.current is not None:
            self.paragraphs.append("".join(self.current))
            self.paragraph_links.append(self.current_links)
            self.current = None
            self.current_links = None


def verify_embed(payload, post):
    try:
        embed = json.loads(payload)
        author_url = urllib.parse.urlsplit(embed["author_url"])
        author = publisher("https://x.com" + author_url.path)
        if (
            author_url.scheme != "https"
            or author_url.netloc.lower() not in {"x.com", "twitter.com"}
            or author_url.query
            or author_url.fragment
            or author != post["author"]
            or embed.get("type") != "rich"
            or (embed.get("provider_name"), embed.get("provider_url"))
            not in {("Twitter", "https://twitter.com"), ("X", "https://x.com")}
        ):
            raise SourceError("Official embed author is doubtful")
        parsed = EmbedReader()
        parsed.feed(embed["html"])
        links = []
        for link in parsed.links:
            url = urllib.parse.urlsplit(link)
            if url.scheme == "https" and url.netloc.lower() in {"x.com", "twitter.com"}:
                links.append(("https://x.com" + url.path).lower())
        created = datetime.fromtimestamp(post["publishedAt"], timezone.utc)
        months = (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        )
        day = f"{months[created.month - 1]} {created.day}, {created.year}"
        dated = any(
            ("https://x.com" + urllib.parse.urlsplit(link).path).lower()
            == post["sourceUrl"]
            and text.strip() == day
            for link, text in parsed.dated_links
        )
        normal = lambda text: " ".join(html.unescape(text).split())
        matches_text = bool(parsed.paragraphs) and normal(
            parsed.paragraphs[0]
        ) == normal(post["text"])
        if not matches_text and post.get("_quotedPostId") and parsed.paragraph_links:
            # Official embeds append a short link for quotes absent from SSR full_text.
            # Accept only that anchored suffix; never discard arbitrary URLs or text.
            paragraph_links = parsed.paragraph_links[0]
            if paragraph_links:
                href, label = paragraph_links[-1]
                matches_text = (
                    re.fullmatch(r"https://t\.co/[A-Za-z0-9]{1,32}", href) is not None
                    and label == href
                    and normal(parsed.paragraphs[0])
                    == normal(post["text"] + " " + href)
                )
        if post["sourceUrl"] not in links or not dated or not matches_text:
            raise SourceError("Official embed does not match the primary post")
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SourceError):
            raise
        raise SourceError("Unsupported official embed") from error


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        original = urllib.parse.urlsplit(req.full_url)
        same_host = target.netloc.lower() == original.netloc.lower()
        official_embed = (
            original.netloc.lower() == "publish.twitter.com"
            and target.netloc.lower() == "publish.x.com"
            and original.path == target.path == "/oembed"
        )
        if (
            target.scheme != "https"
            or not (same_host or official_embed)
            or target.username
            or target.password
        ):
            raise SourceError("Public redirect outside the approved host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; top-mode/0.1)"}
    )
    try:
        with urllib.request.build_opener(PublicRedirects()).open(
            request, timeout=15
        ) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise SourceError("Public response too large")
            return data.decode("utf-8")
    except http.client.HTTPException as error:
        raise SourceError("Incomplete or invalid public HTTP response") from error


def read_public(source, now, limit, getter=fetch):
    posts = profile_posts(getter(source), source, now)[:limit]
    for post in posts:
        url = "https://publish.twitter.com/oembed?" + urllib.parse.urlencode(
            {"url": post["sourceUrl"], "omit_script": "true"}
        )
        verify_embed(getter(url), post)
        post.pop("_quotedPostId", None)
    return posts


def validate_config(config):
    if (
        not isinstance(config, dict)
        or type(config.get("version")) is not int
        or config["version"] != 1
        or type(config.get("enabled")) is not bool
    ):
        raise ValueError("Explicit version-1 watch configuration required")
    sources = config.get("publishers")
    if not isinstance(sources, list) or not sources or len(sources) > 5:
        raise ValueError("One to five approved public publishers required")
    sources = [publisher(s) for s in sources]
    if len(set(sources)) != len(sources):
        raise ValueError("Duplicate publishers")
    for key, low, high in (
        ("intervalHours", 1, 24),
        ("failureNoticeHours", 4, 168),
        ("maximumPosts", 1, 20),
        ("retainedIds", 20, 1000),
    ):
        value = config.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Invalid watch limit: " + key)
    if config["failureNoticeHours"] < config["intervalHours"]:
        raise ValueError("Failure notice must cover at least one polling interval")
    return sources


def poll(config, state, now, reader=read_public):
    """Deterministic transition with injected public reads; output only new notices."""
    sources = validate_config(config)
    now = epoch(now)
    if (
        not isinstance(state, dict)
        or now is None
        or type(state.get("version", 1)) is not int
        or state.get("version", 1) != 1
        or not isinstance(state.get("recentSignals", []), list)
        or not isinstance(state.get("publishers", {}), dict)
    ):
        raise ValueError("Valid state and observation time required")
    result = copy.deepcopy(state)
    result.setdefault("version", 1)
    records = result.setdefault("publishers", {})
    for record in records.values():
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("seenPosts", {}), dict)
            or any(
                not isinstance(url, str) or number(at) is None
                for url, at in record.get("seenPosts", {}).items()
            )
        ):
            raise ValueError("Invalid private watch ledger")
        for key in (
            "baselineAt",
            "replayFloor",
            "lastAttemptAt",
            "nextCheckAt",
            "failureSince",
            "lastSuccessfulCheckAt",
        ):
            if key in record:
                value = epoch(record[key])
                if value is None:
                    raise ValueError("Invalid private watch timestamp")
                record[key] = value
    emitted = []
    if not config["enabled"]:
        return result, emitted
    interval = config["intervalHours"] * 3600
    # Allow bounded scheduler jitter regardless of its phase relative to UTC.
    grace = min(1800, interval / 8)
    for source in sources:
        record = records.setdefault(source, {})
        last_attempt = record.get("lastAttemptAt")
        # Derive eligibility from the real attempt, including older saved deadlines.
        if last_attempt is not None and now < last_attempt + interval - grace:
            continue
        record.setdefault("baselineAt", now)
        record.update(lastAttemptAt=now, nextCheckAt=now + interval - grace)
        try:
            posts = reader(source, now, config["maximumPosts"])
            if not posts:
                raise SourceError("Empty discovery is not complete coverage")
        except (OSError, ValueError) as error:
            record["coverage"] = "unknown"
            record["errorType"] = type(error).__name__
            failed = record.setdefault("failureSince", now)
            if now - failed >= config["failureNoticeHours"] * 3600 and not record.get(
                "failureNoticeEmitted"
            ):
                notice = {
                    "kind": "coverage_failure",
                    "source": source,
                    "observedAt": now,
                    "coverage": "unknown",
                }
                emitted.append(notice)
                record["failureNoticeEmitted"] = True
            continue
        record.update(coverage="partial", lastSuccessfulCheckAt=now)
        record.pop("errorType", None)
        was_failed = record.pop("failureNoticeEmitted", False)
        record.pop("failureSince", None)
        if was_failed:
            emitted.append(
                {
                    "kind": "coverage_recovered",
                    "source": source,
                    "observedAt": now,
                    "coverage": "partial",
                }
            )
        seen = dict(record.get("seenPosts", {}))
        cutoff = max(record["baselineAt"], record.get("replayFloor", 0))
        for post in reversed(posts):
            if post["sourceUrl"] not in seen and post["publishedAt"] > cutoff:
                signal = dict(
                    post,
                    id=hashlib.sha256(post["sourceUrl"].encode()).hexdigest(),
                    kind="needs_interpretation",
                    observedAt=now,
                    verification={"method": "primary_source_read", "verifiedAt": now},
                )
                emitted.append(signal)
                result.setdefault("recentSignals", []).append(signal)
            seen[post["sourceUrl"]] = post["publishedAt"]
        ordered = sorted(seen.items(), key=lambda item: (item[1], item[0]))
        evicted = ordered[: -config["retainedIds"]]
        if evicted:
            record["replayFloor"] = max(
                record.get("replayFloor", 0), max(at for _, at in evicted)
            )
        record["seenPosts"] = dict(ordered[-config["retainedIds"] :])
    result["recentSignals"] = result.get("recentSignals", [])[-50:]
    return result, emitted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--once", action="store_true", help="One due public check, then exit"
    )
    mode.add_argument(
        "--status", action="store_true", help="Print state coverage; performs no HTTP"
    )
    args = parser.parse_args()
    try:
        import fcntl
    except ImportError:
        parser.exit(
            2,
            "Watch requires macOS/Linux file locking; this platform is unsupported.\n",
        )
    try:
        import os

        config = json.loads(args.config.read_text())
        validate_config(config)
        handle = os.open(str(args.state) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(handle, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = json.loads(args.state.read_text()) if args.state.exists() else {}
            if args.status:
                print(json.dumps(state))
                return
            state, signals = poll(config, state, time.time())
            if config["enabled"]:
                write_private(args.state, state)
            if signals:
                print(json.dumps({"signals": signals}))
    except (OSError, ValueError) as error:
        parser.exit(2, "Watch refused: " + type(error).__name__ + "\n")


if __name__ == "__main__":
    main()
