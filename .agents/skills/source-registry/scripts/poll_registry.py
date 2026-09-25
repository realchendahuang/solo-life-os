#!/usr/bin/env python3
"""Poll official changelogs and feeds from sources/registry.json into workspace/candidates/.

This script activates the official source registry as an ingestion pipeline without
relying on external paid search APIs (Grok was removed 2026-09-19).
It uses pure Python standard library (urllib, xml.etree, html, concurrent.futures) to fetch
public feeds/changelogs concurrently, applies word-boundary & negative filtering, classifies
hit-playbook blueprints & friction angles, deduplicates against workspace/candidates/, and
records new candidate signals matching contracts/candidate-signal.schema.json.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_candidate as candidate_mod  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")

# Known public RSS/Atom feeds for official registries when available
KNOWN_FEEDS: dict[str, str] = {
    "openai-product-release-notes": "https://openai.com/news/rss.xml",
    "github-changelog": "https://github.blog/changelog/feed/",
    "cloudflare-developer-platform-changelog": "https://developers.cloudflare.com/changelog/rss/index.xml",
    "vercel-changelog": "https://vercel.com/atom",
    "hacker-news-frontpage": "https://news.ycombinator.com/rss",
    "v2ex-tech-feed": "https://www.v2ex.com/feed/tab/tech.xml",
    "v2ex-creative-feed": "https://www.v2ex.com/feed/tab/creative.xml",
    "lobsters-frontpage": "https://lobste.rs/rss",
    "openchamber-releases": "https://github.com/openchamber/openchamber/releases.atom",
    "ollama-releases": "https://github.com/ollama/ollama/releases.atom",
    "claude-code-releases": "https://github.com/anthropics/claude-code/releases.atom",
    "uv-releases": "https://github.com/astral-sh/uv/releases.atom",
    "llamacpp-releases": "https://github.com/ggml-org/llama.cpp/releases.atom",
    "simonwillison-blog": "https://simonwillison.net/atom/entries/",
    "producthunt-today": "https://www.producthunt.com/feed",
    "ruanyifeng-blog": "https://feeds.feedburner.com/ruanyifeng",
    "danluu-blog": "https://danluu.com/atom.xml",
    "paulgraham-essays": "https://filipesilva.github.io/paulgraham-rss/feed.rss",
    "owenyoung-blog": "https://www.owenyoung.com/feed",
    "huggingface-blog": "https://huggingface.co/blog/feed.xml",
    "arxiv-daily-papers": "https://huggingface.co/api/daily_papers",
    "latent-space": "https://www.latent.space/feed",
    "pragmatic-engineer": "https://newsletter.pragmaticengineer.com/feed",
    "linus-ekenstam-design": "https://linusekenstam.substack.com/feed",
    "v2ex-hot-topics": "https://www.v2ex.com/api/topics/hot.json",
    "nodeseek-discussions": "https://rss.nodeseek.com/",
    "lowendtalk-discussions": "https://lowendtalk.com/discussions/feed.rss",
    "eugeneyan-blog": "https://eugeneyan.com/rss/",
    "chiphuyen-blog": "https://huyenchip.com/feed",
    "mitchellh-blog": "https://mitchellh.com/feed.xml",
    "jvns-blog": "https://jvns.ca/atom.xml",
    "antirez-blog": "https://antirez.com/rss",
    "bytebytego-newsletter": "https://blog.bytebytego.com/feed",
    "martinfowler-bliki": "https://martinfowler.com/feed.atom",
    "swyx-blog": "https://swyx.io/rss.xml",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 X-Tiller/1.0"
)

# Sources whose pages are client-rendered and have no machine-readable feed. Polling them
# over HTTP returns navigation links, which used to be stored as if they were updates, so
# they are reported as manual-capture instead. Their content arrives through the user-level
# web-search skill or through capture_candidate.py.
NO_FEED_SOURCES: frozenset[str] = frozenset({
    "openai-api-changelog",
    "anthropic-claude-release-notes",
    "google-gemini-api-changelog",
    "cursor-changelog",
})

# Sources fetched through the WebBridge daemon against a tab the user has open. These are
# opt-in per run (--webbridge): they act on the user's browser and cannot be reproduced
# from a clean checkout.
WEBBRIDGE_SOURCES: frozenset[str] = frozenset({
    "linuxdo-top-daily",
    "indiehackers-community",
})

# Sources captured one post at a time from an explicit URL; never swept by a poll.
MANUAL_CAPTURE_SOURCES: frozenset[str] = frozenset({"x-direct-signal"})

# One parser per source that does not use a standard RSS/Atom feed.
SPECIAL_PARSERS: dict[str, str] = {
    "github-trending-daily": "github-trending-html",
    "v2ex-hot-topics": "v2ex-hot-json",
    "arxiv-daily-papers": "daily-papers-json",
}


def requires_webbridge(source: dict[str, Any], feed_url: str) -> bool:
    """True when this source must be read out of a browser tab rather than a feed URL."""
    source_id = source.get("id", "")
    if source_id in WEBBRIDGE_SOURCES:
        return True
    if source_id in KNOWN_FEEDS:
        return False
    return "reddit.com" in feed_url


NEGATIVE_FILTERS: list[re.Pattern] = [
    re.compile(r"\bairdrop\b", re.IGNORECASE),
    re.compile(r"\bgiveaway\b", re.IGNORECASE),
    re.compile(r"\bpresale\b", re.IGNORECASE),
    re.compile(r"\bcasino\b", re.IGNORECASE),
    re.compile(r"\btokenomics\b", re.IGNORECASE),
    re.compile(r"\bcdk\b", re.IGNORECASE),
    re.compile(r"公益速来"),
    re.compile(r"发放.*cdk", re.IGNORECASE),
    re.compile(r"领.*cdk", re.IGNORECASE),
    re.compile(r"cdk\s*领取", re.IGNORECASE),
]


def clean_html_text(raw_html: str) -> str:
    """Strip HTML tags and unescape HTML entities to plain excerpt text."""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_feed_xml(xml_content: bytes) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom XML feed into normalized raw items."""
    root = ET.fromstring(xml_content)
    items: list[dict[str, Any]] = []

    # Check Atom namespace (e.g. {http://www.w3.org/2005/Atom}entry)
    atom_ns = ""
    if root.tag.startswith("{"):
        atom_ns = root.tag.split("}")[0] + "}"

    if root.tag.endswith("feed") or atom_ns:
        # Atom feed
        for entry in root.findall(f"{atom_ns}entry"):
            title_elem = entry.find(f"{atom_ns}title")
            title = clean_html_text(title_elem.text or "") if title_elem is not None else ""

            link = ""
            for link_elem in entry.findall(f"{atom_ns}link"):
                rel = link_elem.get("rel", "alternate")
                if rel in {"alternate", ""}:
                    link = link_elem.get("href", "")
                    if link:
                        break

            published_elem = entry.find(f"{atom_ns}published")
            if published_elem is None:
                published_elem = entry.find(f"{atom_ns}updated")
            pub_date = published_elem.text if published_elem is not None else None

            summary_elem = entry.find(f"{atom_ns}summary")
            if summary_elem is None:
                summary_elem = entry.find(f"{atom_ns}content")
            summary = clean_html_text(summary_elem.text or "") if summary_elem is not None else ""
            if summary.strip().lower() == "comments":
                summary = ""

            if title and link:
                items.append({
                    "title": title,
                    "url": link,
                    "published_at": pub_date,
                    "excerpt": summary or title,
                })
    else:
        # RSS 2.0 feed
        channel = root.find("channel")
        channel_root = channel if channel is not None else root
        for item in channel_root.findall("item"):
            title_elem = item.find("title")
            title = clean_html_text(title_elem.text or "") if title_elem is not None else ""

            link_elem = item.find("link")
            link = (link_elem.text or "").strip() if link_elem is not None else ""

            pub_date_elem = item.find("pubDate")
            pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else None

            desc_elem = item.find("description")
            desc = clean_html_text(desc_elem.text or "") if desc_elem is not None else ""
            if desc.strip().lower() == "comments":
                desc = ""

            if title and link:
                items.append({
                    "title": title,
                    "url": link,
                    "published_at": pub_date,
                    "excerpt": desc or title,
                })

    return items


def parse_changelog_html(html_text: str, base_url: str) -> list[dict[str, Any]]:
    """Lightweight fallback heuristic extraction for official changelog HTML pages."""
    items: list[dict[str, Any]] = []
    link_pattern = re.compile(
        r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    seen_urls: set[str] = set()

    for match in link_pattern.finditer(html_text):
        href, anchor_raw = match.groups()
        title = clean_html_text(anchor_raw)
        if len(title) < 10 or len(title) > 160:
            continue
        href_lower = href.lower()
        if not any(token in href_lower for token in ["changelog", "release", "blog", "news", "docs", "202"]):
            continue
        if href.startswith("/"):
            parsed_base = urlsplit(base_url)
            full_url = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
        elif href.startswith("http://") or href.startswith("https://"):
            full_url = href
        else:
            continue
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        items.append({
            "title": title,
            "url": full_url,
            "published_at": None,
            "excerpt": title,
        })
        if len(items) >= 20:
            break
    return items


def parse_daily_papers_json(raw_json: bytes) -> list[dict[str, Any]]:
    """Parse Hugging Face daily papers API payload into normalized candidate items."""
    try:
        data = json.loads(raw_json.decode("utf-8"))
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for entry in data:
        paper = entry.get("paper") or {}
        pid = paper.get("id") or ""
        title = paper.get("title") or entry.get("title") or ""
        summary = paper.get("summary") or entry.get("summary") or ""
        upvotes = int(paper.get("upvotes") or 0)
        published_at = paper.get("publishedAt") or entry.get("publishedAt")

        authors_list = paper.get("authors") or []
        first_author = authors_list[0].get("name") if authors_list and isinstance(authors_list[0], dict) else None

        if not title:
            continue

        arxiv_url = f"https://arxiv.org/abs/{pid}" if pid else entry.get("url") or ""
        if not arxiv_url:
            continue

        items.append({
            "title": title.strip(),
            "url": arxiv_url.strip(),
            "published_at": published_at,
            "excerpt": summary.strip() or title.strip(),
            "author": first_author,
            "upvotes": upvotes,
        })
    return items


def parse_github_trending_html(html_text: str) -> list[dict[str, Any]]:
    """Parse GitHub daily trending HTML page into normalized candidate items."""
    items: list[dict[str, Any]] = []
    articles = re.findall(r'<article class="Box-row">(.*?)</article>', html_text, re.DOTALL)
    for art in articles:
        repo_m = re.search(r'<h2[^>]*>.*?<a[^>]*href="/([^"]+)"', art, re.DOTALL)
        if not repo_m:
            continue
        repo_name = repo_m.group(1).strip()
        repo_url = f"https://github.com/{repo_name}"

        desc_m = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', art, re.DOTALL)
        desc = clean_html_text(desc_m.group(1)) if desc_m else ""

        stars_m = re.search(r'([0-9,]+)\s+stars\s+today', art, re.DOTALL)
        stars_today_raw = stars_m.group(1).replace(",", "") if stars_m else "0"
        try:
            stars_today = int(stars_today_raw)
        except ValueError:
            stars_today = 0

        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)<', art)
        lang = lang_m.group(1).strip() if lang_m else ""

        full_excerpt = f"{desc} [{lang}] (+{stars_today} stars today)".strip()
        items.append({
            "title": f"{repo_name}: {desc}" if desc else repo_name,
            "url": repo_url,
            "published_at": None,
            "excerpt": full_excerpt,
            "author": repo_name.split("/")[0] if "/" in repo_name else None,
            "stars_today": stars_today,
            "language": lang,
        })
    return items


def parse_v2ex_hot_json(raw_json: bytes) -> list[dict[str, Any]]:
    """Parse V2EX hot topics JSON API into normalized candidate items."""
    try:
        data = json.loads(raw_json.decode("utf-8"))
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for topic in data:
        title = topic.get("title") or ""
        url = topic.get("url") or ""
        content = topic.get("content") or ""
        node = topic.get("node", {}).get("title") or ""
        replies = topic.get("replies") or 0
        member = topic.get("member", {}).get("username")

        if not title or not url:
            continue

        excerpt = f"[{node}] {content[:300]} (回复: {replies})".strip()
        items.append({
            "title": title.strip(),
            "url": url.strip(),
            "published_at": None,
            "excerpt": excerpt,
            "author": member,
            "replies": replies,
        })
    return items


def fetch_url(url: str, timeout: float = 10.0) -> bytes:
    """Fetch URL with custom User-Agent and timeout."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def fetch_destination_description(url: str, timeout: float = 3.5) -> str | None:
    """Fetch destination page and extract meta description or opening paragraph for title-only items."""
    if not url or not url.startswith("http"):
        return None
    # Hacker News discussion redirect
    hn_m = re.search(r"news\.ycombinator\.com/item\?id=(\d+)", url)
    if hn_m:
        try:
            req = urllib.request.Request(
                f"https://hacker-news.firebaseio.com/v0/item/{hn_m.group(1)}.json",
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("url"):
                    url = data["url"]
                elif data.get("text"):
                    return clean_html_text(data["text"])[:300]
        except Exception:
            pass

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            chunk = resp.read(40960).decode("utf-8", errors="ignore")
            for pat in [
                r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
                r'<meta\s+content=["\'](.*?)["\']\s+name=["\']description["\']',
                r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']',
                r'<meta\s+content=["\'](.*?)["\']\s+property=["\']og:description["\']',
                r'<meta\s+name=["\']twitter:description["\']\s+content=["\'](.*?)["\']',
            ]:
                m = re.search(pat, chunk, re.I | re.DOTALL)
                if m:
                    desc = clean_html_text(m.group(1))
                    if "github.com" in url:
                        desc = re.sub(r"^[^:]+:\s*", "", desc)
                    if len(desc) >= 20 and not any(bp in desc.lower() for bp in ["cookie", "javascript", "browser"]):
                        return desc[:350]

            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", chunk, re.I | re.DOTALL)
            for p in paragraphs[:6]:
                cp = clean_html_text(p)
                if len(cp) >= 40 and not any(bp in cp.lower() for bp in ["cookie", "javascript"]):
                    return cp[:300]
    except Exception:
        pass
    return None


def fetch_via_webbridge(target_domain: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Fetch page items via local Kimi WebBridge daemon using user's active browser session."""
    bridge_url = "http://127.0.0.1:10086/command"
    find_payload = json.dumps({
        "action": "find_tab",
        "args": {"url": target_domain, "active": True},
        "session": "x-tiller-poll",
    }).encode("utf-8")

    req = urllib.request.Request(bridge_url, data=find_payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            find_res = json.loads(resp.read().decode("utf-8"))
            if not find_res.get("ok"):
                # Tab not currently focused; navigate to it
                nav_payload = json.dumps({
                    "action": "navigate",
                    "args": {"url": target_domain, "newTab": True, "group_title": "x-tiller"},
                    "session": "x-tiller-poll",
                }).encode("utf-8")
                nav_req = urllib.request.Request(bridge_url, data=nav_payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(nav_req, timeout=timeout) as nav_resp:
                    nav_res = json.loads(nav_resp.read().decode("utf-8"))
                    if not nav_res.get("ok"):
                        return []
                time.sleep(2.5)
    except Exception:
        return []

    if "indiehackers" in target_domain:
        js_code = (
            'JSON.stringify(Array.from(document.querySelectorAll("a"))'
            '.filter(a => a.href && a.href.includes("/post/"))'
            '.map(a => ({ title: a.innerText.trim(), url: a.href }))'
            '.filter(it => it.title && it.title.length > 10)'
            '.slice(0, 20))'
        )
    elif "reddit.com" in target_domain:
        time.sleep(2)
        js_code = (
            'JSON.stringify(Array.from(document.querySelectorAll("shreddit-post")).map(p => {'
            '  let permalink = p.getAttribute("permalink") || "";'
            '  let fullUrl = permalink.startsWith("http") ? permalink : "https://www.reddit.com" + permalink;'
            '  return {'
            '    title: p.getAttribute("post-title") || "",'
            '    url: fullUrl,'
            '    score: p.getAttribute("score") || "0",'
            '    comments: p.getAttribute("comment-count") || "0",'
            '    author: p.getAttribute("author") || "",'
            '    subreddit: p.getAttribute("subreddit-prefixed-name") || ""'
            '  };'
            '}).filter(it => it.title && it.url).slice(0, 25))'
        )
    else:
        # Default: LINUX DO topic list
        js_code = (
            'JSON.stringify(Array.from(document.querySelectorAll("tr.topic-list-item")).map(tr => ({'
            '  title: tr.querySelector("a.title")?.innerText?.trim(),'
            '  url: tr.querySelector("a.title")?.href,'
            '  category: tr.querySelector(".badge-category")?.innerText?.trim(),'
            '  views: tr.querySelector(".num.views .number")?.innerText?.trim(),'
            '  replies: tr.querySelector(".num.posts .number")?.innerText?.trim()'
            '})))'
        )

    eval_payload = json.dumps({
        "action": "evaluate",
        "args": {"code": js_code},
        "session": "x-tiller-poll",
    }).encode("utf-8")

    req = urllib.request.Request(bridge_url, data=eval_payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            eval_res = json.loads(resp.read().decode("utf-8"))
            if not eval_res.get("ok"):
                return []
            raw_items = json.loads(eval_res.get("data", {}).get("value", "[]"))
            items: list[dict[str, Any]] = []
            for it in raw_items:
                title = it.get("title")
                item_url = it.get("url")
                if not title or not item_url:
                    continue
                if "reddit.com" in target_domain:
                    score_val = int(it.get("score") or 0)
                    comments = it.get("comments") or "0"
                    sub = it.get("subreddit") or ""
                    excerpt = f"[{sub}] Upvotes: {score_val} | Comments: {comments}"
                    items.append({
                        "title": title,
                        "url": item_url,
                        "published_at": None,
                        "excerpt": excerpt,
                        "author": it.get("author"),
                        "upvotes": score_val,
                        "replies": comments,
                    })
                else:
                    cat = it.get("category") or "Indie"
                    views = it.get("views") or ""
                    reps = it.get("replies") or ""
                    excerpt = f"[{cat}] 浏览:{views} 回复:{reps}" if views else title
                    items.append({
                        "title": title,
                        "url": item_url,
                        "published_at": None,
                        "excerpt": excerpt,
                        "author": None,
                        "views": views,
                        "replies": reps,
                    })
            return items
    except Exception:
        return []


def parse_published_at(value: str | None) -> str | None:
    """Normalize a feed timestamp to ISO 8601 in Shanghai time, or None if unparseable.

    RSS 2.0 `pubDate` is RFC 822 ("Tue, 16 Sep 2026 09:12:00 GMT") and Atom `published` is
    RFC 3339; the old code only tried ISO and silently fell back to "now", which made most
    candidates look freshly published. Returning None keeps the missing value visible
    instead of inventing one.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI).isoformat(timespec="seconds")


def matches_filters(text: str, event_filters: list[str]) -> bool:
    """Smart check if item text matches configured filter keywords with word boundaries."""
    if not event_filters:
        return True

    # Reject spam / irrelevant crypto promotion
    for neg in NEGATIVE_FILTERS:
        if neg.search(text):
            return False

    lower = text.lower()
    for f in event_filters:
        k = f.strip()
        if not k:
            continue
        # Pure ASCII word (e.g. "AI", "Agent", "Git", "Rust"): use word boundary to avoid matching "email", "said"
        if re.fullmatch(r"[A-Za-z0-9_\-\.]+", k):
            if re.search(rf"\b{re.escape(k)}\b", text, re.IGNORECASE):
                return True
        else:
            # CJK / mixed characters: use substring matching
            if k.lower() in lower:
                return True
    return False


def boundary_pattern(token: str) -> str:
    r"""Escape one keyword, adding \b only on sides that start/end with a word character.

    Without this, `cli` matches inside `clients` and `sdk` inside unrelated words, which
    produced large numbers of false blueprint hits. CJK keywords keep substring matching
    because \b has no meaning between CJK characters, and punctuated tokens such as
    `v1.` or `90%` only take the boundary on the side that needs it.
    """
    escaped = re.escape(token)
    if token[:1].isascii() and token[:1].isalnum():
        escaped = r"\b" + escaped
    if token[-1:].isascii() and token[-1:].isalnum():
        escaped = escaped + r"\b"
    return escaped


# Blueprint keywords per hit-playbook structure. Explicit plural/variant forms replace the
# old unprefixed patterns, so `tokens` still matches while `clients` no longer matches `cli`.
BLUEPRINT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "B": (
        "price", "prices", "pricing", "priced", "cost", "costs", "cheaper", "expensive",
        "token", "tokens", "quota", "quotas", "billing", "bill", "bills", "free tier",
        "90%", "10x", "kv cache", "compression", "memory wall", "quantization", "quantized",
        "降价", "计费", "成本", "价格", "额度", "省钱", "按量", "显存",
    ),
    "A": (
        "vulnerability", "vulnerabilities", "cve", "regression", "regressions", "broken",
        "deprecated", "deprecation", "deprecate", "hack", "hacked", "hacks", "leak", "leaks",
        "leaked", "failure", "failures", "failed", "fails", "outage", "outages",
        "under pressure", "trusted", "hallucination", "hallucinations", "benchmark",
        "benchmarks", "empirical", "降智", "翻车", "bug", "故障", "踩坑", "失灵", "暗病", "漏洞",
    ),
    "E": (
        "show hn", "v1.", "v2.", "cli", "sdk", "agent", "agents", "copilot", "release",
        "releases", "released", "harness", "mcp", "sqlite", "git as shared memory",
        "playable world", "做了一个", "开源", "插件", "独立开发", "自动化",
    ),
    "D": (
        "vs", "alternative", "alternatives", "why i left", "why we ditch", "rethinking",
        "rethink", "争论", "站队", "选型", "为什么不", "放弃",
    ),
}

BLUEPRINT_MATCHERS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    key: tuple((kw, re.compile(boundary_pattern(kw), re.IGNORECASE)) for kw in keywords)
    for key, keywords in BLUEPRINT_KEYWORDS.items()
}


def first_blueprint_match(key: str, text: str) -> str | None:
    """Return the first keyword of blueprint `key` that matches, or None."""
    for keyword, matcher in BLUEPRINT_MATCHERS[key]:
        if matcher.search(text):
            return keyword
    return None


def classify_hit_potential(title: str, text: str, source: dict[str, Any]) -> tuple[str, list[str]]:
    """Evaluate candidate against hit-playbook blueprints and content pillars.

    Returns (suggested_action, tags). Every blueprint tag carries the keyword that fired
    (`match:B:price`) so a promoted candidate can be explained later.
    """
    tags: list[str] = [source["id"]]
    source_type = source.get("source_type", "rss")
    tags.append(source_type)

    combined = f"{title} {text}"
    suggested_action = "watch"

    # B: Cost, pricing, quota, extreme ROI, KV Cache, compression, memory wall
    if (hit := first_blueprint_match("B", combined)) is not None:
        tags.extend(["blueprint:B", "friction:cost", f"match:B:{hit}"])
        suggested_action = "brief"

    # A: Reality check, failure, bug, regression, disillusion, evaluation under pressure
    if (hit := first_blueprint_match("A", combined)) is not None:
        tags.extend(["blueprint:A", "friction:reality-check", f"match:A:{hit}"])
        suggested_action = "brief"

    # E: Breakout tool, harness, micro-solution, independent app
    if (hit := first_blueprint_match("E", combined)) is not None:
        tags.extend(["blueprint:E", "tool:breakout", f"match:E:{hit}"])
        if suggested_action == "watch":
            suggested_action = "brief"

    # D: Great debate, technology controversy, alternatives
    if (hit := first_blueprint_match("D", combined)) is not None:
        tags.extend(["blueprint:D", "angle:debate", f"match:D:{hit}"])
        if suggested_action == "watch":
            suggested_action = "brief"

    return suggested_action, list(dict.fromkeys(tags))


def determine_verification_status(source_type: str) -> str:
    """Determine initial verification status matching candidate-signal contract."""
    if source_type in {"official-changelog", "github-releases"}:
        return "official-primary"
    elif source_type in {"official-blog"}:
        return "corroborated"
    return "unverified"


def poll_source(
    source: dict[str, Any],
    repo: Path,
    *,
    dry_run: bool = False,
    fetch_network: bool = True,
    sample_xml: bytes | None = None,
    max_items: int = 30,
    use_webbridge: bool = False,
) -> dict[str, Any]:
    """Poll a single official source and persist discovered candidates."""
    source_id = source["id"]
    feed_url = KNOWN_FEEDS.get(source_id) or source.get("source_url")
    candidates_dir = repo / "workspace" / "candidates" / source_id
    event_filters = source.get("event_filters", [])

    result: dict[str, Any] = {
        "source_id": source_id,
        "feed_url": feed_url,
        "polled": False,
        "items_found": 0,
        "matched_filter": 0,
        "new_candidates": [],
        "errors": [],
    }

    if not feed_url:
        result["errors"].append("no source_url configured")
        return result

    if source_id in MANUAL_CAPTURE_SOURCES:
        result["errors"].append(
            "manual capture source: use capture_x_signal.py --url for individual posts"
        )
        return result

    if source_id in NO_FEED_SOURCES:
        result["errors"].append(
            "no machine-readable feed: capture manually (web-search skill or capture_candidate.py)"
        )
        return result

    if requires_webbridge(source, feed_url):
        if not fetch_network:
            result["polled"] = True
            return result
        if not use_webbridge:
            result["errors"].append(
                "requires --webbridge (reads an open Chrome tab via the WebBridge daemon)"
            )
            return result
        items = fetch_via_webbridge(feed_url)
        if not items:
            result["errors"].append(f"webbridge tab not found or extraction failed (make sure {feed_url} is open in Chrome)")
            return result
        result["polled"] = True
    else:
        raw_content: bytes | None = sample_xml
        if raw_content is None:
            if not fetch_network:
                result["polled"] = True
                return result
            try:
                raw_content = fetch_url(feed_url)
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"fetch failed: {exc}")
                return result

        result["polled"] = True
        items: list[dict[str, Any]] = []
        parser = SPECIAL_PARSERS.get(source_id)
        if parser == "github-trending-html":
            items = parse_github_trending_html(raw_content.decode("utf-8", errors="replace"))
            if not items:
                result["errors"].append("github trending html parse returned 0 items")
                return result
        elif parser == "v2ex-hot-json":
            items = parse_v2ex_hot_json(raw_content)
            if not items:
                result["errors"].append("v2ex hot json parse returned 0 items")
                return result
        elif parser == "daily-papers-json" or feed_url.endswith(".json"):
            # Only the daily-papers endpoint is JSON. Matching on "/api/" here used to send
            # HTML changelogs such as developers.openai.com/api/docs/changelog into this
            # parser, where they silently produced zero items.
            items = parse_daily_papers_json(raw_content)
            if not items:
                result["errors"].append("daily papers json parse returned 0 items")
                return result
        else:
            try:
                items = parse_feed_xml(raw_content)
            except Exception as exc:  # noqa: BLE001
                # Try HTML fallback for non-XML changelog web pages
                try:
                    items = parse_changelog_html(raw_content.decode("utf-8", errors="replace"), feed_url)
                except Exception:
                    pass
                if not items:
                    result["errors"].append(f"xml parse failed: {exc}")
                    return result

    # Cap to the newest items to prevent huge historical feeds from stalling. Feeds are not
    # guaranteed to be newest-first, and appending all new candidates every poll is
    # wasteful, so order by publish date before slicing. Items with no parseable date sort
    # last: they may be new, but they cannot claim to be the newest.
    if max_items > 0 and len(items) > max_items:
        items.sort(key=lambda it: parse_published_at(it.get("published_at")) or "", reverse=True)
        items = items[:max_items]

    result["items_found"] = len(items)
    now = datetime.now(SHANGHAI)
    pending_records: list[dict[str, Any]] = []
    for item in items:
        # Strict anti-pattern: reject pure version tag dumps without meaningful description
        title_stripped = item['title'].strip()
        if re.match(r"^(Release\s+)?v?\d+\.\d+(\.\d+)?(-[a-z0-9\.]*)?$", title_stripped, re.I):
            if not item.get('excerpt') or len(item['excerpt']) < 30 or item['excerpt'] == item['title']:
                continue

        # Auto-enrich missing or trivial excerpts by fetching destination description
        if not item.get('excerpt') or item['excerpt'] == item['title'] or len(item['excerpt']) < 30:
            dest_desc = fetch_destination_description(item['url'])
            if dest_desc:
                item['excerpt'] = dest_desc

        full_text = f"{item['title']} {item['excerpt']}"
        upvotes = item.get("upvotes", 0)

        # Anti-Echo-Chamber Barbell Filter for arXiv / research papers:
        # 1. High community resonance (upvotes >= 40): Breakout paradigm shifts outside current bubble (auto-pass)
        # 2. Focused vertical (upvotes >= 10): Must match core event filters (agent, cache, eval, benchmark, etc.)
        is_breakthrough = False
        if source_id == "arxiv-daily-papers":
            if upvotes >= 40:
                is_breakthrough = True
            elif upvotes >= 10 and matches_filters(full_text, event_filters):
                pass
            else:
                continue
        else:
            if not matches_filters(full_text, event_filters):
                continue

        result["matched_filter"] += 1

        # Normalize to ISO 8601; an unparseable or missing feed date stays null rather than
        # being replaced by the fetch time, which would fake freshness.
        pub_iso = parse_published_at(item.get("published_at"))

        item_url = item["url"].strip()
        if item_url.startswith("http://"):
            item_url = "https://" + item_url[7:]

        verification_status = determine_verification_status(source.get("source_type", ""))
        suggested_action, tags = classify_hit_potential(item["title"], item["excerpt"], source)

        stars_today = item.get("stars_today", 0)

        if upvotes:
            tags.append(f"upvotes:{upvotes}")
        if is_breakthrough:
            tags.append("breakthrough")
            tags.append("cross-domain")
            suggested_action = "brief"

        if source_id == "github-trending-daily":
            tags.append("blueprint:E")
            tags.append("tool:breakout")
            if stars_today:
                tags.append(f"stars_today:{stars_today}")
            if stars_today >= 500:
                suggested_action = "brief"
        elif "reddit.com" in feed_url:
            if upvotes >= 200:
                suggested_action = "brief"

        args = argparse.Namespace(
            source_id=source_id,
            url=item_url,
            title=item["title"],
            excerpt=item["excerpt"][:500],
            author=item.get("author"),
            published_at=pub_iso,
            verification_status=verification_status,
            suggested_action=suggested_action,
            tag=tags,
            output=None,
            dry_run=dry_run,
        )

        try:
            candidate_record = candidate_mod.build_candidate(args, now, source)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"candidate build failed for {item['url']}: {exc}")
            continue

        existing = candidate_mod.find_duplicate(repo / "workspace" / "candidates", candidate_record)
        if existing:
            continue

        # Buffer records and write them in one batch after the loop.
        pending_records.append(candidate_record)
        candidate_mod.register_candidate_cache(candidate_record, candidate_mod.candidates_ledger_path(repo / "workspace" / "candidates"))

        result["new_candidates"].append({
            "id": candidate_record["id"],
            "title": candidate_record["title"],
            "url": candidate_record["canonical_url"],
            "action": suggested_action,
            "tags": tags,
        })

    if pending_records and not dry_run:
        for candidate_record in pending_records:
            candidate_mod.append_candidate_ledger(repo / "workspace" / "candidates", candidate_record)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll official sources from sources/registry.json into workspace/candidates/."
    )
    parser.add_argument("--source-id", help="Poll only the specified source ID.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect feed without writing candidates.")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Skip outbound network requests (reports registry readiness).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Concurrent worker threads for polling multiple sources (default 6).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum items to evaluate per feed (default 30).",
    )
    parser.add_argument(
        "--webbridge",
        action="store_true",
        help="Opt in to polling browser-tab sources via the WebBridge daemon "
             "(opens/reads tabs in the user's Chrome).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = candidate_mod.find_repo_root()
        sources_dict = candidate_mod.load_sources(repo / "sources" / "registry.json", repo)
    except candidate_mod.CandidateError as exc:
        print(f"[poll-registry] error: {exc}", file=sys.stderr)
        return 2

    target_sources = [
        s for s in sources_dict.values()
        if s.get("enabled", True) and (not args.source_id or s.get("id") == args.source_id)
    ]

    if not target_sources:
        print(f"[poll-registry] no matching enabled sources for {args.source_id!r}", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []

    if args.no_network or len(target_sources) == 1 or args.concurrency <= 1:
        for source in target_sources:
            res = poll_source(
                source,
                repo,
                dry_run=args.dry_run,
                fetch_network=not args.no_network,
                max_items=args.limit,
                use_webbridge=args.webbridge,
            )
            results.append(res)
    else:
        max_workers = min(args.concurrency, len(target_sources))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_source = {
                executor.submit(
                    poll_source,
                    source,
                    repo,
                    dry_run=args.dry_run,
                    fetch_network=True,
                    max_items=args.limit,
                    use_webbridge=args.webbridge,
                ): source
                for source in target_sources
            }
            for future in as_completed(future_to_source):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as exc:  # noqa: BLE001
                    s = future_to_source[future]
                    results.append({
                        "source_id": s.get("id", "unknown"),
                        "feed_url": s.get("source_url"),
                        "polled": False,
                        "items_found": 0,
                        "matched_filter": 0,
                        "new_candidates": [],
                        "errors": [f"worker exception: {exc}"],
                    })

    # Sort results deterministically by source_id
    results.sort(key=lambda r: r.get("source_id", ""))

    print(
        json.dumps(
            {
                "mode": "dry-run" if args.dry_run else ("checked" if args.no_network else "polled"),
                "sources_polled": len(results),
                "total_new_candidates": sum(len(r["new_candidates"]) for r in results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
