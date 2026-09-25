"""CLI — argument-compatible with v1 ``scripts/fetch_tweet.py``.

Same flags, same JSON envelopes, same exit codes:
  0 = success / no new mentions
  1 = error / new mentions found (--monitor)
  2 = monitor setup error
New in v2: errors carry an additional machine-readable ``error_code``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from . import config
from .ledger import archive_tweets, ledger_stats, query_ledger
from .backends.fxtwitter import supplement_views
# local patch (X-Tiller): documented upper bound for --limit.
from .backends.nitter import MAX_LIMIT as MAX_REQUESTED_LIMIT
from .exceptions import XtfError
from .i18n import set_lang, t
from .monitor import monitor_mentions
from .parsers.urls import extract_list_id, parse_article_id, parse_tweet_url
from .router import Router


def _emit(result: Dict[str, Any], pretty: bool) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2 if pretty else None))


def _fail(result: Dict[str, Any], exc: XtfError) -> Dict[str, Any]:
    result["error"] = str(exc) or exc.code
    result["error_code"] = exc.code
    if getattr(exc, "causes", None):
        result["error_causes"] = {k: str(v) for k, v in exc.causes.items()}
    return result


def _supplement_and_report(tweets):
    """local patch (X-Tiller): return (tweets, real view-supplement stats)."""
    stats = supplement_views(tweets)
    return tweets, stats


def _archive_if_requested(args, result: Dict[str, Any], tweet_dicts) -> None:
    """Archive fetched tweet dicts when --ledger is set (never fatal).

    Without --ledger this is a no-op, keeping legacy behavior identical.
    """
    if not args.ledger:
        return
    if result.get("error") or not tweet_dicts:
        return
    db = Path(args.ledger).expanduser()
    try:
        report = archive_tweets(
            db, tweet_dicts, source=f"xtf:{result.get('backend', 'fetch')}"
        )
        result["ledger"] = report
    except Exception as exc:  # archiving must not break a successful fetch
        result["ledger_error"] = f"{type(exc).__name__}: {exc}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xtf",
        description=(
            "Fetch tweets from X/Twitter.\n"
            "  --url <URL>              Single tweet via FxTwitter (zero deps)\n"
            "  --url <URL> --replies    Tweet replies via Nitter / browser\n"
            "  --user <username>        User timeline via Nitter / browser\n"
            "  --search <query>         Search tweets via Nitter\n"
            "  --user-info <username>   User profile via FxTwitter\n"
            "  --article <URL_or_ID>    X Article full text via browser\n"
            "  --monitor @username      Monitor X mentions (incremental, cron-friendly)\n"
            "  --list <list_url_or_id>  Fetch tweets from an X List via browser\n"
            "\n"
            "Backends: auto (default, Nitter first then browser), nitter, browser.\n"
            "Configure Nitter instances via XTF_NITTER=url1,url2 (see README)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", "-u", help="Tweet URL (x.com or twitter.com)")
    parser.add_argument("--user", help="X/Twitter username (without @)")
    parser.add_argument("--search", "-s", metavar="QUERY", help="Search tweets (via Nitter)")
    parser.add_argument("--user-info", metavar="USERNAME", help="Get user profile info (via FxTwitter)")
    parser.add_argument("--article", "-a", metavar="URL_or_ID",
                        help="X Article URL (https://x.com/i/article/ID) or bare article ID")
    parser.add_argument("--monitor", "-m", metavar="@USERNAME",
                        help="Monitor X mentions for a username")
    parser.add_argument("--list", "-l", metavar="LIST_URL_OR_ID",
                        help="Fetch tweets from an X List (URL or ID, requires browser)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max tweets for --user / max results for --monitor "
                             "(default: 50 for --user, 10 for --monitor; max 200)")
    parser.add_argument("--replies", "-r", action="store_true", help="Fetch replies")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty print JSON")
    parser.add_argument("--text-only", "-t", action="store_true", help="Human-readable output")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Request timeout in seconds for HTTP backends "
                             "(default: 30 for FxTwitter, 15 for Nitter, 8 page-wait for browser)")
    parser.add_argument("--page-delay", type=float, default=1.0,
                        help="Seconds to sleep between Nitter paginated requests (default: 1.0)")
    parser.add_argument("--max-reply-recursion", type=int, default=None,
                        help="Max nested-reply pages to expand (default: 20)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Browser (Camofox) port (default: {config.DEFAULT_BROWSER_PORT})")
    parser.add_argument("--nitter", default=None,
                        help="Nitter instance(s), comma-separated. Overrides XTF_NITTER.")
    parser.add_argument("--backend", choices=["auto", "nitter", "browser"], default="auto",
                        help="Backend: nitter (direct HTTP), browser (Camofox/Playwright), auto (nitter first, browser fallback)")
    parser.add_argument("--browser-driver", choices=["camofox", "playwright"], default=None,
                        help="Browser driver (default: XTF_BROWSER env or camofox)")
    parser.add_argument("--ledger", metavar="DB",
                        help="SQLite ledger DB. With a fetch mode: archive results after fetch. "
                             "With --query/--stats: search/inspect the archive without fetching.")
    parser.add_argument("--query", metavar="TERM",
                        help="Search archived tweets by keyword (requires --ledger)")
    parser.add_argument("--stats", action="store_true",
                        help="Show ledger statistics (requires --ledger)")
    parser.add_argument("--lang", default=None, choices=["zh", "en"],
                        help="Output language for tool messages: zh (default) or en")
    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_lang(args.lang or config.default_lang())
    pretty = args.pretty

    modes = [bool(args.url), bool(args.user), bool(args.search),
             bool(args.user_info), bool(args.article), bool(args.monitor), bool(args.list)]
    ledger_mode = bool(args.query or args.stats)
    if ledger_mode and not args.ledger:
        print(t("err_prefix") + "--query/--stats require --ledger <db>", file=sys.stderr)
        sys.exit(1)
    if args.query and args.stats:
        print(t("err_prefix") + "--query and --stats are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if sum(modes) + int(ledger_mode) > 1:
        print(t("err_mutually_exclusive"), file=sys.stderr)
        sys.exit(1)
    if not any(modes):
        if not args.ledger or not ledger_mode:
            parser.print_help()
            sys.exit(1)

    # local patch (X-Tiller): --limit is None until the mode picks its default,
    # so an explicit --limit 50 is never silently downgraded to the monitor default.
    DEFAULT_TIMELINE_LIMIT = 50
    DEFAULT_MONITOR_LIMIT = 10
    timeline_limit = args.limit if args.limit is not None else DEFAULT_TIMELINE_LIMIT
    monitor_limit = args.limit if args.limit is not None else DEFAULT_MONITOR_LIMIT
    if timeline_limit < 1:
        print(t("err_prefix") + "--limit must be at least 1", file=sys.stderr)
        sys.exit(1)
    # local patch (X-Tiller): cap --limit at a documented maximum.
    if timeline_limit > MAX_REQUESTED_LIMIT:
        print(
            f"[xtf] --limit {timeline_limit} exceeds the maximum "
            f"{MAX_REQUESTED_LIMIT}; clamping",
            file=sys.stderr,
        )
        timeline_limit = MAX_REQUESTED_LIMIT
    monitor_limit = min(monitor_limit, MAX_REQUESTED_LIMIT)

    # ── Ledger-only modes: query / stats (no fetch) ─────────────────────
    if args.ledger and ledger_mode:
        db = Path(args.ledger).expanduser()
        result: Dict[str, Any] = {"ledger": str(db)}
        try:
            if args.query:
                hits = query_ledger(db, keyword=args.query, limit=timeline_limit)
                for hit in hits:
                    hit.pop("raw_json", None)  # keep CLI output compact
                result.update({"query": args.query, "count": len(hits), "tweets": hits})
            else:
                result["stats"] = ledger_stats(db)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["error_code"] = "ledger_error"
            _emit(result, pretty)
            sys.exit(1)
        _emit(result, pretty)
        sys.exit(0)

    nitter_instances = None
    if args.nitter:
        nitter_instances = [config._normalize_instance(p) for p in args.nitter.split(",") if p.strip()]

    router = Router(
        backend=args.backend,
        nitter_instances=nitter_instances,
        browser_driver=args.browser_driver,
        browser_port=args.port,
        browser_nitter=nitter_instances[0] if nitter_instances else None,
        # local patch (X-Tiller): None keeps each backend's documented default.
        timeout=args.timeout,
    )
    # local patch (X-Tiller): inter-page politeness + bounded reply recursion.
    router.nitter.page_delay = max(0.0, args.page_delay)
    if args.max_reply_recursion is not None:
        router.browser.max_reply_recursion = max(0, args.max_reply_recursion)

    # ── Mode: Search ─────────────────────────────────────────────────────
    if args.search:
        result: Dict[str, Any] = {"query": args.search}
        try:
            tweets = [tw.to_dict() for tw in router.search(args.search, limit=timeline_limit)]
            result.update({"tweets": tweets, "count": len(tweets), "backend": router.last_backend})
        except XtfError as e:
            _fail(result, e)
        _archive_if_requested(args, result, result.get("tweets", []))
        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            print(f'搜索 "{args.search}" — {result["count"]} 条结果\n')
            for i, tw in enumerate(result["tweets"], 1):
                print(f"[{i}] {tw.get('author_name','')} ({tw.get('author','')}) · {tw.get('time_ago','')}")
                print(f"     {tw.get('text','')[:200]}")
                print(f"     ❤ {tw.get('likes',0)}  💬 {tw.get('replies',0)}  👁 {tw.get('views',0)}")
                print()
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: User Info ──────────────────────────────────────────────────
    if args.user_info:
        result = {}
        try:
            result = router.fetch_user_info(args.user_info)
        except XtfError as e:
            result = _fail({"username": args.user_info}, e)
        if args.text_only:
            if result.get("error"):
                print(f"错误: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(f"@{result.get('username','')} ({result.get('display_name','')})")
            if result.get("bio"):
                print(f"简介: {result['bio']}")
            print(f"推文: {result.get('tweets_count',0)} | 关注: {result.get('following',0)} | 粉丝: {result.get('followers',0)}")
            if result.get("joined"):
                print(f"加入: {result['joined']}")
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: Mentions monitor ───────────────────────────────────────────
    if args.monitor:
        use_nitter = args.backend == "nitter" or (
            args.backend == "auto" and router.nitter.available()
        )
        result = monitor_mentions(router, args.monitor, limit=monitor_limit,
                                  use_nitter=use_nitter)
        if result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(2)
        if result.get("is_baseline"):
            if not args.text_only:
                _emit(result, pretty)
            sys.exit(0)
        new_mentions = result.get("new_mentions", [])
        if args.text_only:
            if new_mentions:
                print(t("monitor_header", username=result["username"], count=len(new_mentions)) + "\n")
                for idx, m in enumerate(new_mentions, 1):
                    print(f"[{idx}] {m['title']}")
                    print(f"     {m['url']}")
                    if m.get("snippet"):
                        print(f"     {m['snippet'][:120]}")
                    print()
        else:
            _emit(result, pretty)
        sys.exit(1 if new_mentions else 0)

    # ── Mode: User timeline ──────────────────────────────────────────────
    if args.user:
        result = {"username": args.user, "limit": timeline_limit}
        try:
            tweets = [tw.to_dict() for tw in router.fetch_timeline(args.user, limit=timeline_limit)]
            tweets, view_stats = _supplement_and_report(tweets)
            result.update({
                "tweets": tweets, "count": len(tweets),
                "backend": router.last_backend,
                "views_supplemented": view_stats["filled"],
                "views_supplement_requested": view_stats["requested"],
            })
            if not tweets:
                result["warning"] = t("warn_no_tweets")
        except XtfError as e:
            _fail(result, e)
        _archive_if_requested(args, result, result.get("tweets", []))
        _print_timeline_result(result, args, header=t("timeline_header", user=args.user,
                                                      count=result.get("count", 0)))
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: X Article ──────────────────────────────────────────────────
    if args.article:
        if args.backend == "nitter":
            print("[warning] --article requires a browser backend. "
                  "Nitter cannot fetch X Articles. Falling back to browser.", file=sys.stderr)
        article_id = parse_article_id(args.article)
        if not article_id:
            print(t("err_prefix") + t("err_invalid_article", input=args.article), file=sys.stderr)
            sys.exit(1)
        result = {"article_id": article_id}
        try:
            article = router.fetch_article(article_id)
            result = article.to_dict()
            if article.is_partial:
                result["warning"] = t("article_login_note")
        except XtfError as e:
            _fail(result, e)
        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            title = result.get("title") or "(no title)"
            author = result.get("author") or result.get("author_handle") or ""
            print(t("article_header", title=title))
            if author:
                print(f"@{result.get('author_handle', '').lstrip('@') or author}  {author}")
            print(t("article_words", word_count=result.get("word_count", 0)))
            if result.get("warning"):
                print(f"⚠️  {result['warning']}")
            print()
            print(result.get("content") or "(empty)")
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: Tweet replies ──────────────────────────────────────────────
    if args.url and args.replies:
        try:
            username, tweet_id = parse_tweet_url(args.url)
        except ValueError as e:
            _emit({"url": args.url, "error": str(e), "error_code": "invalid_input"}, pretty)
            sys.exit(1)
        result = {"url": args.url, "username": username, "tweet_id": tweet_id}
        try:
            replies = [r.to_dict() for r in router.fetch_replies(username, tweet_id)]
            replies, view_stats = _supplement_and_report(replies)
            result.update({
                "replies": replies, "reply_count": len(replies),
                "count": len(replies), "backend": router.last_backend,
                "views_supplemented": view_stats["filled"],
                "views_supplement_requested": view_stats["requested"],
            })
            if not replies:
                result["warning"] = t("warn_no_replies")
        except XtfError as e:
            _fail(result, e)
        if args.ledger:
            # Mark every reply as a reply to the parent tweet so the ledger
            # archives them with is_reply=1. Prefer any backend-provided value.
            parent_id = result.get("tweet_id") or ""
            for reply in result.get("replies", []):
                reply.setdefault("in_reply_to_status_id", parent_id)
        _archive_if_requested(args, result, result.get("replies", []))
        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            print(t("replies_header", url=args.url) + "\n")
            for idx, r in enumerate(result.get("replies", []), 1):
                print(f"[{idx}] {r['author_name']} ({r['author']}) · {r.get('time_ago', '')}")
                print(f"     {r['text']}")
                stats = f"     ❤ {r['likes']}  💬 {r['replies']}  👁 {r['views']}"
                if r.get("media"):
                    stats += "  " + t("media_label_with_urls", n=len(r["media"]),
                                      urls=", ".join(r["media"]))
                print(stats)
                print()
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: X List ─────────────────────────────────────────────────────
    if args.list:
        list_id = extract_list_id(args.list)
        if not list_id:
            print(t("err_prefix") + t("err_invalid_list", input=args.list), file=sys.stderr)
            sys.exit(1)
        result = {"list_id": list_id, "limit": timeline_limit}
        try:
            tweets = [tw.to_dict() for tw in router.fetch_list(list_id, limit=timeline_limit)]
            tweets, view_stats = _supplement_and_report(tweets)
            result.update({
                "tweets": tweets, "count": len(tweets),
                "backend": router.last_backend,
                "views_supplemented": view_stats["filled"],
                "views_supplement_requested": view_stats["requested"],
            })
            if not tweets:
                result["warning"] = t("warn_no_tweets")
        except XtfError as e:
            _fail(result, e)
        _archive_if_requested(args, result, result.get("tweets", []))
        _print_timeline_result(result, args, header=t("list_header", list_id=list_id,
                                                      count=result.get("count", 0)))
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: Single tweet via FxTwitter ─────────────────────────────────
    try:
        username, tweet_id = parse_tweet_url(args.url)
    except ValueError as e:
        result = {"url": args.url, "error": str(e), "error_code": "invalid_input"}
        _emit(result, pretty)
        sys.exit(1)

    result = {"url": args.url, "username": username, "tweet_id": tweet_id}
    try:
        result["tweet"] = router.fetch_tweet(username, tweet_id)
    except XtfError as e:
        _fail(result, e)
    if result.get("tweet") and not result.get("error"):
        # fxtwitter dicts carry no tweet_id; inject the one from the URL.
        # local patch (X-Tiller): the backend has already verified the payload
        # id/handle, so this injection can no longer mislabel a mirror response.
        tweet_dict = dict(result["tweet"])
        tweet_dict.setdefault("tweet_id", result.get("tweet_id") or "")
        # local patch (X-Tiller): surface which metric keys upstream actually
        # reported, at payload level too, so a real 0 is distinguishable from
        # a missing value. Additive: existing fields are untouched.
        if isinstance(result["tweet"].get("metrics_present"), list):
            result["metrics_present"] = list(result["tweet"]["metrics_present"])
        _archive_if_requested(args, result, [tweet_dict])
    else:
        _archive_if_requested(args, result, [])

    if args.text_only:
        tweet = result.get("tweet", {})
        canonical_url = (
            f"https://x.com/{tweet.get('screen_name') or username}/status/"
            f"{tweet.get('tweet_id') or tweet_id}"
        )
        if tweet.get("is_article") and tweet.get("article", {}).get("full_text"):
            article = tweet["article"]
            print(f"# {article['title']}\n")
            print(t("article_by", screen_name=tweet["screen_name"],
                    created_at=tweet.get("created_at", "")))
            print(t("article_stats", likes=tweet["likes"], retweets=tweet["retweets"],
                    views=tweet["views"]))
            print(t("article_words", word_count=article["word_count"]) + "\n")
            print(article["full_text"])
            # local patch (X-Tiller): text-only output must carry the source URL.
            print(f"\nURL: {canonical_url}")
        elif tweet.get("text"):
            print(f"@{tweet['screen_name']}: {tweet['text']}")
            print(t("tweet_stats", likes=tweet["likes"], retweets=tweet["retweets"],
                    views=tweet["views"]))
            print(f"URL: {canonical_url}")
        else:
            # local patch (X-Tiller): never exit 0 with empty stdout. A tweet
            # dict with neither article.full_text nor text is an error.
            error = result.get("error") or t("err_empty_tweet")
            if not result.get("error"):
                result["error"] = error
                result["error_code"] = "empty_tweet"
            print(t("err_prefix") + error, file=sys.stderr)
            print(f"[error_code={result.get('error_code', 'error')}]", file=sys.stderr)
            sys.exit(1)
    else:
        _emit(result, pretty)

    sys.exit(1 if result.get("error") else 0)


def _print_timeline_result(result: Dict[str, Any], args, header: str) -> None:
    if args.text_only:
        if result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(1)
        print(header + "\n")
        for idx, tw in enumerate(result.get("tweets", []), 1):
            print(f"[{idx}] {tw['author_name']} ({tw['author']}) · {tw.get('time_ago', '')}")
            print(f"     {tw['text']}")
            stats = f"     ❤ {tw['likes']}  💬 {tw['replies']}  👁 {tw['views']}"
            if tw.get("media"):
                stats += "  " + t("media_label", n=len(tw["media"]))
            print(stats)
            print()
    else:
        _emit(result, args.pretty)


if __name__ == "__main__":
    main()
