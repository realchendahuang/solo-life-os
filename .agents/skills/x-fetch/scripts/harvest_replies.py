#!/usr/bin/env python3
"""Harvest high-quality reply threads from an X post via local Kimi WebBridge.

Part of the 3-stage rocket flywheel (Stage 2: Harvest & Triage).
Extracts, deduplicates, and filters comments from high-signal threads/probes,
producing structured JSON and Markdown briefs for follow-up synthesis.

Usage:
    python3 harvest_replies.py --url https://x.com/<user>/status/<id>
    python3 harvest_replies.py --active
    python3 harvest_replies.py --url <url> --max-scrolls 30 --output workspace/research/my_thread.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DAEMON_URL = "http://127.0.0.1:10086/command"
DEFAULT_SESSION = "x-tiller-harvest"
SHANGHAI = ZoneInfo("Asia/Shanghai")

STATUS_ID_RE = re.compile(r"status/(\d+)")
SPAM_PATTERNS = [
    re.compile(r"返\s*\d+.*(?:visa|卡|usdt|返利)", re.I),
    re.compile(r"(?:cdk|激活码|发号|代充|白嫖福利|加v|私聊我)", re.I),
    re.compile(r"^[\s\U00010000-\U0010ffff\u2600-\u27bf\U0001f300-\U0001f9ff]+$"), # pure emojis
]


def post_command(action: str, args: dict, session: str = DEFAULT_SESSION, timeout: float = 30.0) -> dict:
    payload = json.dumps({"action": action, "args": args, "session": session}).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def evaluate_js(code: str, session: str = DEFAULT_SESSION) -> any:
    res = post_command("evaluate", {"code": code}, session=session)
    if not res.get("ok"):
        raise RuntimeError(f"WebBridge evaluate failed: {res.get('error')}")
    val = res.get("data", {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def parse_numeric(text: str) -> int:
    if not text:
        return 0
    clean = re.sub(r"[^\d\.万kKmM]", "", text)
    if not clean:
        return 0
    multiplier = 1
    if "万" in clean:
        multiplier = 10000
        clean = clean.replace("万", "")
    elif "k" in clean.lower():
        multiplier = 1000
        clean = re.sub(r"[kK]", "", clean)
    elif "m" in clean.lower():
        multiplier = 1000000
        clean = re.sub(r"[mM]", "", clean)
    try:
        return int(float(clean) * multiplier)
    except Exception:
        return 0


def is_spam(author: str, text: str) -> bool:
    combined = f"{author} {text}"
    return any(p.search(combined) for p in SPAM_PATTERNS)


JS_EXTRACT_ALL = """(() => {
  const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
  return JSON.stringify(articles.map(a => {
    const userEl = a.querySelector('[data-testid="User-Name"]');
    const textEl = a.querySelector('[data-testid="tweetText"]');
    const linkEl = a.querySelector('a[href*="/status/"]');
    const likeEl = a.querySelector('[data-testid="like"]');
    const replyEl = a.querySelector('[data-testid="reply"]');
    const timeEl = a.querySelector('time');

    let fullUser = userEl ? userEl.innerText.replace(/\\n+/g, ' ') : '';
    let screenName = '';
    const m = fullUser.match(/@([a-zA-Z0-9_]+)/);
    if (m) screenName = m[1];

    let likesStr = likeEl ? (likeEl.getAttribute('aria-label') || likeEl.innerText || '') : '';
    let repliesStr = replyEl ? (replyEl.getAttribute('aria-label') || replyEl.innerText || '') : '';

    return {
      user_full: fullUser,
      screen_name: screenName,
      text: textEl ? textEl.innerText.trim() : '',
      url: linkEl ? linkEl.href : '',
      likes_raw: likesStr,
      replies_raw: repliesStr,
      datetime: timeEl ? timeEl.getAttribute('datetime') : ''
    };
  }));
})()"""


def harvest(
    target_url: str | None = None,
    use_active: bool = False,
    max_scrolls: int = 25,
    scroll_pause: float = 1.2,
    keep_spam: bool = False,
) -> dict:
    session = DEFAULT_SESSION

    # 1. Connect or navigate
    if target_url:
        m = STATUS_ID_RE.search(target_url)
        target_status_id = m.group(1) if m else None

        # Check active tab first
        tab_res = post_command("find_tab", {"url": "x.com", "active": True}, session=session)
        current_url = tab_res.get("data", {}).get("url", "")

        if not target_status_id or target_status_id not in current_url:
            print(f"[harvest] Navigating active tab to {target_url}...")
            nav_res = post_command("navigate", {"url": target_url, "newTab": False}, session=session)
            if not nav_res.get("ok"):
                raise RuntimeError(f"Failed to navigate: {nav_res}")
            time.sleep(3.0)
    else:
        tab_res = post_command("find_tab", {"url": "x.com", "active": True}, session=session)
        if not tab_res.get("ok"):
            raise RuntimeError("No active X tab found. Please open an X post in Chrome or provide --url.")
        current_url = tab_res.get("data", {}).get("url", "")
        m = STATUS_ID_RE.search(current_url)
        target_status_id = m.group(1) if m else None
        target_url = current_url

    if not target_status_id:
        raise ValueError(f"Could not identify status ID from {target_url}")

    print(f"[harvest] Connected to post {target_status_id} ({target_url})")

    # Start from top
    evaluate_js("window.scrollTo(0, 0);", session=session)
    time.sleep(1.0)

    # 2. Scroll and collect
    all_tweets: dict[str, dict] = {}
    root_tweet: dict | None = None
    no_new_consecutive = 0

    print(f"[harvest] Scanning reply thread (up to {max_scrolls} scrolls)...")
    for step in range(1, max_scrolls + 1):
        items = evaluate_js(JS_EXTRACT_ALL, session=session)
        if not isinstance(items, list):
            items = []

        new_in_step = 0
        for item in items:
            raw_url = item.get("url", "")
            sm = STATUS_ID_RE.search(raw_url)
            status_id = sm.group(1) if sm else None
            if not status_id:
                continue

            # Identify root tweet
            if status_id == target_status_id:
                if not root_tweet and item.get("text"):
                    root_tweet = {
                        "id": status_id,
                        "user": item.get("user_full", ""),
                        "screen_name": item.get("screen_name", ""),
                        "text": item.get("text", ""),
                        "url": f"https://x.com/{item.get('screen_name', 'i')}/status/{status_id}",
                        "datetime": item.get("datetime", ""),
                    }
                continue

            if status_id not in all_tweets:
                likes_num = parse_numeric(item.get("likes_raw", ""))
                replies_num = parse_numeric(item.get("replies_raw", ""))
                spam = is_spam(item.get("user_full", ""), item.get("text", ""))

                all_tweets[status_id] = {
                    "id": status_id,
                    "user": item.get("user_full", ""),
                    "screen_name": item.get("screen_name", ""),
                    "text": item.get("text", ""),
                    "url": f"https://x.com/{item.get('screen_name', 'i')}/status/{status_id}",
                    "likes": likes_num,
                    "replies": replies_num,
                    "datetime": item.get("datetime", ""),
                    "is_spam": spam,
                }
                new_in_step += 1

        if new_in_step == 0:
            no_new_consecutive += 1
        else:
            no_new_consecutive = 0

        # Terminate if bottom reached
        if no_new_consecutive >= 3:
            print(f"[harvest] Bottom of replies reached at scroll step {step}.")
            break

        evaluate_js("window.scrollBy(0, 800);", session=session)
        time.sleep(scroll_pause)

    # Scroll back to top
    evaluate_js("window.scrollTo(0, 0);", session=session)

    # Filter and sort
    replies_list = list(all_tweets.values())
    if not keep_spam:
        valid_replies = [r for r in replies_list if not r["is_spam"] and r["text"]]
        spam_count = len(replies_list) - len(valid_replies)
    else:
        valid_replies = [r for r in replies_list if r["text"]]
        spam_count = 0

    # Sort primarily by likes (desc), then by reply length
    valid_replies.sort(key=lambda r: (r["likes"], len(r["text"])), reverse=True)

    result = {
        "status_id": target_status_id,
        "target_url": target_url,
        "harvested_at": datetime.now(SHANGHAI).isoformat(),
        "root_tweet": root_tweet,
        "total_extracted": len(all_tweets),
        "spam_filtered": spam_count,
        "valid_count": len(valid_replies),
        "replies": valid_replies,
    }
    return result


def export_markdown_report(data: dict, out_path: Path) -> str:
    root = data.get("root_tweet") or {}
    replies = data.get("replies", [])

    lines = [
        f"# 评论区精华收割简报: {data.get('status_id')}",
        "",
        f"- **原帖链接**: {data.get('target_url')}",
        f"- **原帖作者**: {root.get('user', '未知')}",
        f"- **收割时间**: {data.get('harvested_at')}",
        f"- **统计概览**: 共捕获 {data.get('valid_count')} 条有效回复（已去噪过滤 {data.get('spam_filtered')} 条）",
        "",
        "## 原帖正文",
        "",
        f"> {root.get('text', '（未捕获到根贴正文）')}",
        "",
        "## 高赞与深度回复清单（按互动降序）",
        "",
    ]

    for idx, r in enumerate(replies, 1):
        likes_str = f" [👍 {r['likes']}]" if r['likes'] > 0 else ""
        lines.append(f"{idx}. **{r['user']}**{likes_str}")
        lines.append(f"   {r['text']}")
        lines.append(f"   *链接*: {r['url']}")
        lines.append("")

    content = "\n".join(lines)
    out_path.write_text(content, encoding="utf-8")
    return content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="Target X post URL")
    parser.add_argument("--active", action="store_true", help="Use current active tab in Chrome")
    parser.add_argument("--max-scrolls", type=int, default=25, help="Max scrolls down (default: 25)")
    parser.add_argument("--scroll-pause", type=float, default=1.2, help="Pause between scrolls in seconds")
    parser.add_argument("--keep-spam", action="store_true", help="Do not filter spam/rebate accounts")
    parser.add_argument("--output", help="Custom output JSON path")
    parser.add_argument("--markdown", action="store_true", default=True, help="Generate companion markdown brief")

    args = parser.parse_args()

    if not args.url and not args.active:
        parser.error("Either --url <URL> or --active must be provided.")

    try:
        data = harvest(
            target_url=args.url,
            use_active=args.active,
            max_scrolls=args.max_scrolls,
            scroll_pause=args.scroll_pause,
            keep_spam=args.keep_spam,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    # Save JSON
    root_id = data["status_id"]
    repo_root = Path(__file__).resolve().parents[4]
    research_dir = repo_root / "workspace" / "research"
    research_dir.mkdir(parents=True, exist_ok=True)

    json_path = Path(args.output) if args.output else research_dir / f"replies-{root_id}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✔ JSON saved to: {json_path}")

    # Save Markdown
    if args.markdown:
        md_path = json_path.with_suffix(".md")
        export_markdown_report(data, md_path)
        print(f"✔ Markdown brief saved to: {md_path}")

    print("\n" + "=" * 50)
    print(f"🎉 收割完成！有效回复: {data['valid_count']} 条 | 去噪过滤: {data['spam_filtered']} 条")
    print("=" * 50)
    for i, r in enumerate(data["replies"][:10], 1):
        like_tag = f" [👍 {r['likes']}]" if r['likes'] > 0 else ""
        print(f"{i}. {r['user']}{like_tag}: {r['text'][:60]}")
    if len(data["replies"]) > 10:
        print(f"... 还有 {len(data['replies']) - 10} 条已保存至报告")
    print("=" * 50)


if __name__ == "__main__":
    main()
