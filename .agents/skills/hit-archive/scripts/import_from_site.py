#!/usr/bin/env python3
"""Incremental importer: sync posts from chendahuang.com into the archive.

Two sources, both deduplicated by post URL against the existing archive:

- default: https://chendahuang.com/highlights — the user's curated highlight
  cards (title, full body text, stats, X URL), imported as kind: hit.
- --mirror: https://chendahuang.com/mirror.json — every post unfiltered with
  verbatim text and live metrics, imported as kind: published. Best for
  keeping "every published post" complete; re-run any time.

The site owner is the user, so this imports their own archived content.

Usage:
    python3 import_from_site.py [--html /tmp/highlights.html] [--dry-run]
    python3 import_from_site.py --mirror [--json /tmp/mirror.json] [--dry-run]
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from frontmatter import load_all, next_free_id, write

SHANGHAI = ZoneInfo("Asia/Shanghai")
SITE_URL = "https://chendahuang.com/highlights"
MIRROR_URL = "https://chendahuang.com/mirror.json"
TWITTER_DATE = "%a %b %d %H:%M:%S %z %Y"


def find_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "profile").is_dir():
            return parent
    raise SystemExit("cannot locate the X-Tiller repository root")


def fetch_html(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    req = urllib.request.Request(SITE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def fetch_mirror(path: str | None) -> dict:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    req = urllib.request.Request(MIRROR_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def next_published_id(posts_dir: Path, day: str) -> str:
    post_id, _target = next_free_id(posts_dir, f"post-{day}-")
    return post_id


def import_mirror(payload: dict, posts_dir: Path, dry_run: bool) -> int:
    """Import every not-yet-archived mirror post as kind: published."""
    fetched_at = payload.get("fetched_at", "")
    snap_label = fetched_at[:16].replace("T", " ")
    existing: set[str] = set()
    for _p, meta, _b in load_all(posts_dir):
        if meta.get("post_url"):
            existing.add(meta["post_url"].split("?")[0].rstrip("/").rsplit("/", 1)[-1])

    missing = [p for p in payload.get("posts", []) if p.get("id") and p["id"] not in existing]
    missing.sort(key=lambda p: p.get("date") or "")
    print(f"mirror fetched_at={fetched_at}: {len(payload.get('posts', []))} posts, "
          f"{len(missing)} new to archive")

    day = datetime.now(SHANGHAI).strftime("%Y%m%d")
    written = 0
    for post in missing:
        # next_published_id reserves the id by creating the file, so a --dry-run
        # preview must not call it: it would leave empty archives behind.
        post_id = f"post-{day}-???" if dry_run else next_published_id(posts_dir, day)
        metrics = {
            key: post[key]
            for key in ("views", "likes", "reposts", "replies", "bookmarks")
            if isinstance(post.get(key), int)
        }
        try:
            posted_at = datetime.strptime(post["date"], TWITTER_DATE).isoformat()
        except (KeyError, ValueError):
            posted_at = post.get("date_bj", "")
        meta = {
            "id": post_id,
            "kind": "published",
            "post_url": post["url"],
            "posted_at": posted_at,
            "collected_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "channel": "unknown",
            "source": "chendahuang.com/mirror",
        }
        if metrics:
            meta["metrics"] = metrics
        body = (post.get("text") or "").strip()
        body += f"\n\n## 我的批注\n\n（为什么这条值得学/为什么它能爆？）\n\n## 数据回采\n- {snap_label} snapshot: "
        body += " ".join(f"{k}={metrics[k]}" for k in ("views", "likes", "reposts", "replies", "bookmarks") if k in metrics)
        body += "\n"
        if not dry_run:
            write(posts_dir / f"{post_id}.md", meta, body)
        written += 1
    print(f"written {written} archives" + (" (dry-run)" if dry_run else ""))
    return 0


def clean(text: str) -> str:
    text = re.sub(r"<!--\[-->" , "", text)
    text = re.sub(r"<!--\]-->", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmlmod.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_stats(text: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    for key, alias in (("likes", "赞"), ("bookmarks", "收藏"), ("reposts", "转发"), ("views", "浏览")):
        m = re.search(rf"([\d.]+[kKwW万]?)\s*{alias}", text)
        if m:
            raw = m.group(1).lower().replace("w", "万").replace("k", "k")
            if "万" in raw:
                stats[key] = int(float(raw.replace("万", "")) * 10000)
            elif raw.endswith("k"):
                stats[key] = int(float(raw[:-1]) * 1000)
            else:
                stats[key] = int(float(raw))
    return stats


def parse_articles(html_text: str) -> list[dict]:
    articles = re.findall(r"<article[^>]*>(.*?)</article>", html_text, re.S)
    out: list[dict] = []
    for raw in articles:
        title_m = re.search(r"<h3[^>]*>(.*?)</h3>", raw, re.S)
        url_m = re.search(r'href="(https://x\.com/realchendahuang/status/\d+)"', raw)
        if not title_m or not url_m:
            continue
        title = clean(title_m.group(1))
        url = url_m.group(1)
        # body: content between stats + h3 and the hidden 在 X 查看原文 link
        body_m = re.search(r"</h3>(.*?)(?:在 X 查看原文|<article)", raw, re.S)
        body = clean(body_m.group(1)) if body_m else ""
        body = re.sub(r"^\d{4}年\d{1,2}月\d{1,2}日[\s\S]*?浏览\s*", "", body, flags=re.S)
        stats = parse_stats(raw)
        date_m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw)
        posted_at = ""
        if date_m:
            y, mo, d = date_m.groups()
            posted_at = f"{y}-{int(mo):02d}-{int(d):02d}T00:00:00+08:00"
        out.append({"title": title, "url": url, "body": body, "stats": stats, "posted_at": posted_at})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", help="use a saved HTML file instead of fetching")
    ap.add_argument("--json", help="use a saved mirror.json file instead of fetching")
    ap.add_argument("--mirror", action="store_true",
                    help="import every unfiltered post from chendahuang.com/mirror.json (kind: published)")
    ap.add_argument("--dry-run", action="store_true", help="print a manifest only")
    args = ap.parse_args()

    root = find_root()
    posts_dir = root / "workspace" / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    if args.mirror:
        return import_mirror(fetch_mirror(args.json), posts_dir, args.dry_run)

    html_text = fetch_html(args.html)
    articles = parse_articles(html_text)
    print(f"parsed {len(articles)} articles")

    root = find_root()
    posts_dir = root / "workspace" / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for a in articles:
            print(f"  {a['posted_at'][:10]} {a['stats']} {a['title'][:30]}")
        return 0

    day = datetime.now(SHANGHAI).strftime("%Y%m%d")
    existing = {
        meta.get("post_url").split("?")[0]
        for _p, meta, _b in load_all(posts_dir)
        if meta.get("post_url")
    }
    written = 0
    skipped = 0
    for a in articles:
        url = a["url"].split("?")[0]
        if url in existing:
            skipped += 1
            continue
        existing.add(url)
        post_id, _target = next_free_id(posts_dir, f"hit-site-{day}-")
        meta = {
            "id": post_id,
            "kind": "hit",
            "post_url": url,
            "collected_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "posted_at": a["posted_at"],
            "channel": "unknown",
            "source": "chendahuang.com/highlights",
            "site_title": a["title"],
        }
        if a["stats"]:
            meta["metrics"] = a["stats"]
        body = f"# {a['title']}\n\n{a['body']}\n\n## 我的批注\n\n（为什么这条值得学/为什么它能爆？）\n"
        write(posts_dir / f"{post_id}.md", meta, body)
        written += 1
    print(f"written {written} new archives, skipped {skipped} already archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())