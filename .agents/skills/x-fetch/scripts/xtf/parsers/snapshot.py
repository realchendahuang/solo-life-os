"""Parsers for Camofox/Playwright aria snapshots of Nitter and X pages.

All functions here are pure: string in, dict/list out. No network, no I/O.
Extracted verbatim from the original fetch_tweet.py to preserve
battle-tested behavior.

# local patch (X-Tiller): the upstream note claimed these parsers were
# "locked by tests/fixtures snapshot tests"; tests/fixtures/ does not exist in
# this checkout. Any real coverage must come from synthetic in-repo snapshots.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional

def _parse_stats_from_text(raw: str) -> tuple:
    """Parse stats numbers from Nitter text line like 'content  1   22  4,418'.

    Nitter renders stats as plain numbers separated by spaces (no icon chars on timeline).
    Returns (cleaned_text, replies, retweets, likes, views).
    """
    # Pattern 0: stats-only line (no text prefix), e.g. " 7  9  83 " or "  6  3  39 "
    stat_only = re.match(
        r"^\s*(\d[\d,]*)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s*[^\d]*$",
        raw.rstrip(),
    )
    if stat_only:
        nums = [int(stat_only.group(i).replace(",", "")) for i in (1, 2, 3)]
        return "", nums[0], nums[1], nums[2], 0

    # Pattern 1: text content followed by 2–4 space-separated numbers at end
    # e.g. "我已经打通...  1   22  4,418"
    # Numbers may have commas (thousands separator)
    stat_match = re.search(
        r"^(.*?)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s*[^\d]*$",
        raw.rstrip(),
    )
    if stat_match:
        text_part = stat_match.group(1).strip()
        nums = [int(stat_match.group(i).replace(",", "")) for i in (2, 3, 4)]
        # Nitter columns: replies | retweets | likes (views sometimes separate)
        return text_part, nums[0], nums[1], nums[2], 0

    # Only 2 trailing numbers
    stat_match2 = re.search(
        r"^(.*?)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s*[^\d]*$",
        raw.rstrip(),
    )
    if stat_match2:
        text_part = stat_match2.group(1).strip()
        nums = [int(stat_match2.group(i).replace(",", "")) for i in (2, 3)]
        return text_part, nums[0], 0, nums[1], 0

    # Private-use unicode icon stats (from replies page or some Nitter versions)
    # Icon stats: \ue803=replies \ue80c=retweets \ue801=likes \ue800=views
    # Numbers are OPTIONAL — Nitter omits them when value is 0
    icon_match = re.search(
        r"\ue803\s*(\d[\d,]*)?\s*\ue80c\s*(\d[\d,]*)?\s*\ue801\s*(\d[\d,]*)?\s*\ue800",
        raw,
    )
    if icon_match:
        prefix = raw[:icon_match.start()].strip()
        def _icon_int(g):
            return int(g.replace(",", "")) if g else 0
        return (
            prefix,
            _icon_int(icon_match.group(1)),
            _icon_int(icon_match.group(2)),
            _icon_int(icon_match.group(3)),
            0,
        )

    # No stats found — clean any icon chars and return raw text
    cleaned = re.sub(r"\s*[\ue800-\ue8ff]\s*[\d,]+", "", raw).strip()
    return cleaned, 0, 0, 0, 0


def parse_timeline_snapshot(snapshot: str, limit: int = 20) -> List[Dict]:
    """Parse Nitter user/list timeline page snapshot into tweet list.

    Handles retweets (``XXX retweeted``), quoted tweets (nested status
    anchors), and inline @mentions split across multiple text/link lines.
    """
    tweets = []
    lines = snapshot.split("\n")
    n = len(lines)

    # ── Step 1: collect all bare-link tweet anchors ────────────────────────
    all_anchors = []  # (line_index, status_path, user, status_id)
    for i in range(n - 1):
        line = lines[i].strip()
        if not re.match(r'^- link \[e\d+\]:$', line):
            continue
        url_line = lines[i + 1].strip()
        url_match = re.match(r'^- /url:\s+(/(\w+)/status/(\d+)#m)$', url_line)
        if url_match:
            all_anchors.append((i, url_match.group(1), url_match.group(2), url_match.group(3)))

    # ── Step 2: separate TOC anchors from content anchors ─────────────────
    def _is_content_anchor(anchor_idx: int) -> bool:
        i = all_anchors[anchor_idx][0]
        for j in range(i + 2, min(n, i + 8)):
            stripped = lines[j].strip()
            if re.match(r'^- link "[^"]+"\s*(\[e\d+\])?:?$', stripped):
                return True
            if stripped.startswith("- text:"):
                return True
            if re.match(r'^- link \[e\d+\]:$', stripped):
                # Could be avatar/profile link — check if its URL is a
                # profile (no /status/) vs another tweet anchor
                if j + 1 < n:
                    next_url = lines[j + 1].strip()
                    url_m = re.match(r'^- /url:\s+(/\w+)$', next_url)
                    if url_m:
                        # Profile link (e.g. /username) — skip, keep looking
                        continue
                return False
            if stripped.startswith("- list:"):
                return False
        return False

    content_anchors = [
        a for idx, a in enumerate(all_anchors)
        if _is_content_anchor(idx)
    ]

    # ── Step 2b: for each anchor, check if "retweeted" appears within ─────
    # 5 lines after it. If so, the anchor's tweet was retweeted by someone.
    # Also detect if a second status anchor appears in the same block (= quote).
    
    # First, build tweet card boundaries.
    # Each card starts at an anchor. A card ends where the next card starts.
    # But a "quoted" anchor (second anchor inside a card) is NOT a card start.
    #
    # Heuristic: an anchor is a "quote" if the anchor immediately before it
    # (in content_anchors) has a different user AND this anchor appears
    # within 30 lines AND there is NO "retweeted" marker between them.
    # Actually simpler: a quote anchor's user differs from the preceding
    # card's primary user, AND there's tweet text between them.
    
    # Simpler approach: just mark anchors that have a "retweeted" line
    # within lines [anchor+1 .. anchor+5]. Those are primary card anchors.
    # Non-retweeted anchors that have tweet text before them from the
    # previous anchor are quotes.
    
    # Let's just use the fact that a quoted tweet's anchor appears AFTER
    # the main tweet's text content. So if we see text content (not just
    # author/handle/time) between anchor N-1 and anchor N, then N is a quote.

    # 如果没有找到任何内容锚点，直接返回空列表
    if not content_anchors:
        return tweets

    primary_indices = [0]  # first anchor is always primary
    quoted_set = set()     # indices into content_anchors that are quotes

    for idx in range(1, len(content_anchors)):
        prev_i = content_anchors[idx - 1][0]
        curr_i = content_anchors[idx][0]
        
        # A quoted tweet appears AFTER the main tweet text but BEFORE
        # the stats line. If we see a stats-only line between anchors,
        # that means the previous tweet's content is complete and this
        # anchor starts a NEW card, not a quote.
        has_tweet_text = False
        has_stats_line = False
        for j in range(prev_i + 2, curr_i):
            stripped = lines[j].strip()
            if stripped.startswith("- text:"):
                raw = stripped[len("- text:"):].strip()
                if not raw:
                    continue
                if re.search(r"retweeted\s*$", raw, re.I):
                    continue
                if raw == "Replying to":
                    continue
                # Check for stats-only line (e.g. "  7  9  83 ")
                _, rc, rt, lk, vw = _parse_stats_from_text(raw)
                if lk or rc or vw:
                    tp = raw
                    stat_m = re.search(r"\s{2,}\d[\d,]*\s{2,}\d[\d,]*", raw)
                    if stat_m:
                        tp = raw[:stat_m.start()].strip()
                    if len(tp) <= 15:
                        has_stats_line = True
                        continue
                if len(raw) > 15:
                    has_tweet_text = True

        # If prev anchor is itself a quote, curr can't be a quote of a quote
        prev_is_quote = (idx - 1) in quoted_set
        
        # Quote only if: has text, NO stats line after it, and prev isn't a quote
        if has_tweet_text and not has_stats_line and not prev_is_quote:
            quoted_set.add(idx)
        else:
            primary_indices.append(idx)

    # ── Helper to parse a block of lines into tweet fields ────────────────
    def _parse_block(start, end, status_id=""):
        author_name = None
        author_handle = None
        time_ago = None
        text_parts = []
        stats_set = False
        likes = rt_count = replies_count = views = 0
        media_urls = []

        for j in range(start, min(end, start + 80)):
            line = lines[j].strip()

            if not author_name:
                m = re.match(r'^- link "([^@#][^"]*?)"\s*(\[e\d+\])?:?$', line)
                if m:
                    name = m.group(1).strip()
                    skip = (
                        re.match(r'^\d+[smhd]$', name)
                        or re.match(r'^[A-Z][a-z]{2} \d+', name)
                        or name.lower() in (
                            "nitter", "logo", "more replies",
                            "tweets", "tweets & replies", "media", "search",
                            "pinned tweet", "retweeted",
                        )
                        or name == ""
                    )
                    if not skip:
                        author_name = name

            if not author_handle:
                m = re.match(r'^- link "@(\w+)"\s*(\[e\d+\])?:?$', line)
                if m:
                    author_handle = "@" + m.group(1)

            if not time_ago:
                m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', line)
                if m:
                    time_ago = m.group(1)
            if not time_ago:
                m = re.match(r'^- link "([A-Z][a-z]{2} \d+(?:, \d{4})?)"\s*(\[e\d+\])?:?$', line)
                if m:
                    time_ago = m.group(1)

            if line.startswith("- text:"):
                raw = line[len("- text:"):].strip()
                if not raw:
                    continue
                if re.match(r'^.+\s+retweeted\s*$', raw):
                    continue
                if raw == "Replying to":
                    continue
                text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)
                if (lk or rc or vw) and not stats_set:
                    likes, rt_count, replies_count, views = lk, rt, rc, vw
                    stats_set = True
                if text_part:
                    skip_labels = {"pinned tweet", "retweeted", ""}
                    if text_part.strip().lower() not in skip_labels:
                        text_parts.append(text_part.strip())

            url_m = re.match(r'^- /url:\s+(/pic/orig/(.+))$', line)
            if url_m:
                decoded = urllib.parse.unquote(url_m.group(2))
                if decoded.startswith("media/"):
                    mu = "https://pbs.twimg.com/media/" + decoded[6:]
                    if mu not in media_urls:
                        media_urls.append(mu)

        tweet_text = " ".join(text_parts).strip() if text_parts else None
        if not tweet_text or not author_handle:
            return None
        entry = {
            "author": author_handle,
            "author_name": author_name or author_handle,
            "text": tweet_text,
            "time_ago": time_ago or "",
            "likes": likes, "retweets": rt_count,
            "replies": replies_count, "views": views,
            "tweet_id": status_id,
        }
        if media_urls:
            entry["media"] = media_urls
        return entry

    # ── Step 3: parse each primary tweet card ──────────────────────────────
    for pi_pos, pi in enumerate(primary_indices):
        if len(tweets) >= limit:
            break

        start_i = content_anchors[pi][0]
        # End at next primary anchor
        if pi_pos + 1 < len(primary_indices):
            end_i = content_anchors[primary_indices[pi_pos + 1]][0]
        else:
            end_i = n

        # Detect "retweeted" marker within first 5 lines after anchor
        retweeted_by = None
        for j in range(start_i + 1, min(start_i + 6, n)):
            stripped = lines[j].strip()
            if stripped.startswith("- text:"):
                raw = stripped[len("- text:"):].strip()
                rt_m = re.match(r'^(.+?)\s+retweeted\s*$', raw)
                if rt_m:
                    retweeted_by = rt_m.group(1).strip()
                    break

        # Find quoted tweet anchor (if any)
        quote_start = end_i
        for qidx in range(pi + 1, len(content_anchors)):
            if content_anchors[qidx][0] >= end_i:
                break
            if qidx in quoted_set:
                quote_start = content_anchors[qidx][0]
                break

        # Parse main tweet (up to quote boundary)
        entry = _parse_block(start_i, quote_start, content_anchors[pi][3])
        if not entry:
            continue

        if retweeted_by:
            entry["retweeted_by"] = retweeted_by

        # Parse quoted tweet
        if quote_start < end_i:
            q_entry = _parse_block(quote_start, end_i)
            if q_entry:
                entry["quoted_tweet"] = q_entry

        # Deduplicate - for retweets, include retweeted_by in key to preserve different retweeters
        if entry.get("retweeted_by"):
            # Retweets: key includes retweeted_by so different people retweeting same content aren't deduped
            key = (entry["retweeted_by"], entry["text"][:80])
        else:
            key = (entry["author"], entry["text"][:80])
        if not any((t.get("retweeted_by") or t["author"], t["text"][:80]) == key for t in tweets):
            tweets.append(entry)

    return tweets



def parse_replies_snapshot(snapshot: str, original_author: str) -> List[Dict]:
    """Parse replies from Nitter tweet page snapshot.

    Each reply block in Nitter looks like:
      - link [eN]:           ← reply permalink (url /author/status/ID#m)
      - link "AuthorName":   ← replier display name
      - link "@handle":      ← replier handle
      - link "12h":          ← time ago (OR "Feb 15" for older)
      - text: Replying to    ← reply marker
      - link "@original":    ← who they replied to
      - text: reply content  ← actual text (may have stats at end)
      - link [eN]:           ← optional media
      - text:  1  0  60      ← optional stats-only line
    """
    replies = []
    lines = snapshot.split("\n")
    n = len(lines)

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == "- text: Replying to":
            author_handle = None
            author_name = None
            reply_text = None
            reply_tweet_id = None  # 新增：回复的 tweet ID（用于递归抓嵌套）
            time_ago = None
            likes = 0
            replies_count = 0
            views = 0
            media_urls = []
            links = []  # 新增：提取评论中的链接
            thread_replies = []  # 新增：嵌套回复
            stats_set = False

            # Scan backwards for author info (within ~15 lines)
            for j in range(i - 1, max(0, i - 15), -1):
                prev = lines[j].strip()

                # Extract reply tweet ID from permalink: /url: /author/status/12345#m
                if not reply_tweet_id:
                    tid_m = re.match(r'^- /url:\s+/\w+/status/(\d+)#m$', prev)
                    if tid_m:
                        reply_tweet_id = tid_m.group(1)

                # @handle (not the original author)
                if not author_handle:
                    m = re.match(r'^- link "@(\w+)"\s*(\[e\d+\])?:?$', prev)
                    if m and m.group(1).lower() != original_author.lower():
                        author_handle = f"@{m.group(1)}"

                # Display name (not time, not nav items)
                if not author_name:
                    m = re.match(r'^- link "([^@#][^"]*?)"\s*(\[e\d+\])?:?$', prev)
                    if m:
                        name = m.group(1).strip()
                        is_time = bool(
                            re.match(r'^\d+[smhd]$', name)
                            or re.match(r'^[A-Z][a-z]{2} \d+', name)
                        )
                        is_skip = name.lower() in (
                            "nitter", "logo", "more replies", ""
                        )
                        if not is_time and not is_skip:
                            author_name = name

                # Timestamp (short: "12h") or date ("Feb 15")
                if not time_ago:
                    m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', prev)
                    if m:
                        time_ago = m.group(1)
                if not time_ago:
                    m = re.match(r'^- link "([A-Z][a-z]{2} \d+(?:, \d{4})?)"\s*(\[e\d+\])?:?$', prev)
                    if m:
                        time_ago = m.group(1)

                if author_handle and author_name and time_ago:
                    break

            # Scan forward for reply text and media (skip "@original" link line)
            for j in range(i + 1, min(n, i + 20)):
                fwd = lines[j].strip()

                # Skip the "@original_author" line right after "Replying to"
                if re.match(r'^- link "@\w+"\s*(\[e\d+\])?:?$', fwd):
                    continue

                if fwd.startswith("- text:"):
                    raw = fwd[len("- text:"):].strip()
                    if not raw:
                        continue

                    text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)

                    # Capture stats once
                    if (lk or rc or vw) and not stats_set:
                        likes = lk
                        replies_count = rc
                        views = vw
                        stats_set = True

                    if text_part and not reply_text:
                        skip_labels = {"replying to", ""}
                        if text_part.strip().lower() not in skip_labels:
                            reply_text = text_part.strip()

                # Media URL line
                url_match = re.match(r'^- /url:\s+(/pic/orig/(.+))$', fwd)
                if url_match:
                    encoded = url_match.group(2)
                    decoded = urllib.parse.unquote(encoded)
                    if decoded.startswith("media/"):
                        media_file = decoded[6:]
                        media_url = f"https://pbs.twimg.com/media/{media_file}"
                        if media_url not in media_urls:
                            media_urls.append(media_url)

                # Link URL line: extract from /url: lines following any link element
                link_url_match = re.match(r'^- /url:\s+(.+)$', fwd)
                if link_url_match:
                    url_part = link_url_match.group(1).strip()
                    # Skip media URLs (already handled above)
                    if not url_part.startswith("/pic/"):
                        decoded_url = urllib.parse.unquote(url_part)
                        # Filter out relative paths and keep valid URLs
                        if decoded_url.startswith("http"):
                            if decoded_url not in links:
                                links.append(decoded_url)

                # Named link where the link text itself is a URL:
                # e.g. - link "https://github.com/some/repo":
                named_link_match = re.match(r'^- link "([^"]+)"\s*(\[e\d+\])?:?$', fwd)
                if named_link_match:
                    link_text = named_link_match.group(1).strip()
                    if link_text.startswith("http"):
                        if link_text not in links:
                            links.append(link_text)

                # Stop at next "Replying to" block - but collect nested replies first
                if fwd == "- text: Replying to":
                    # Continue scanning for nested replies within this thread
                    # Skip the @original line and continue parsing nested content
                    nested_reply_text = None
                    nested_time_ago = None
                    nested_likes = 0
                    nested_replies_count = 0
                    nested_views = 0
                    
                    for k in range(j + 1, min(n, j + 15)):
                        nested_line = lines[k].strip()
                        
                        # Skip @handle lines
                        if re.match(r'^- link "@\w+"\s*(\[e\d+\])?:?$', nested_line):
                            continue
                            
                        # Check for timestamp
                        if not nested_time_ago:
                            m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', nested_line)
                            if m:
                                nested_time_ago = m.group(1)
                        
                        # Parse nested reply text
                        if nested_line.startswith("- text:"):
                            raw = nested_line[len("- text:"):].strip()
                            if raw:
                                text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)
                                if text_part and not nested_reply_text:
                                    skip_labels = {"replying to", ""}
                                    if text_part.strip().lower() not in skip_labels:
                                        nested_reply_text = text_part.strip()
                                        nested_likes = lk
                                        nested_replies_count = rc
                                        nested_views = vw
                        
                        # Stop at next "Replying to" block
                        if nested_line == "- text: Replying to":
                            break
                    
                    if nested_reply_text:
                        thread_replies.append({
                            "text": nested_reply_text,
                            "time_ago": nested_time_ago,
                            "likes": nested_likes,
                            "replies": nested_replies_count,
                            "views": nested_views
                        })
                    
                    # Now break for the main loop
                    break

            if author_handle and reply_text:
                reply = {
                    "author": author_handle,
                    "author_name": author_name or author_handle,
                    "text": reply_text,
                    "time_ago": time_ago,
                    "likes": likes,
                    "replies": replies_count,
                    "views": views,
                }
                if reply_tweet_id:
                    reply["tweet_id"] = reply_tweet_id
                if media_urls:
                    reply["media"] = media_urls
                if links:
                    reply["links"] = links
                if thread_replies:
                    reply["thread_replies"] = thread_replies

                # Deduplicate
                if not any(
                    r["author"] == author_handle and r["text"] == reply_text
                    for r in replies
                ):
                    replies.append(reply)

        i += 1

    return replies


# ---------------------------------------------------------------------------
# High-level feature functions
# ---------------------------------------------------------------------------

def extract_next_cursor(snapshot: str) -> Optional[str]:
    """Extract the next-page cursor from a Nitter timeline snapshot.

    Nitter aria snapshot format for the "Load more" link:
        - link "Load more" [eN]:
          - /url: "?cursor=XXXXXX"

    Returns the raw cursor string (URL-decoded), or None if not found.
    """
    lines = snapshot.split("\n")
    for i, line in enumerate(lines):
        if 'link "Load more"' in line:
            # Next line should be the /url: line
            for j in range(i + 1, min(len(lines), i + 4)):
                url_line = lines[j].strip()
                m = re.match(r'^- /url:\s+"?\?cursor=([^"&\s]+)"?', url_line)
                if m:
                    return urllib.parse.unquote(m.group(1))
    return None

def parse_article_snapshot(snapshot: str) -> Dict[str, Any]:
    """Parse an X Article page snapshot (Camofox aria snapshot) into structured data.

    X Article accessibility tree structure (observed):
      - heading "Article title"          ← article title
      - text: @AuthorHandle              ← author handle
      - text: Author Name                ← author display name
      - text: <date>                     ← publish date
      - text: paragraph 1
      - text: paragraph 2
      ...

    Because X requires login for full content, the snapshot may only contain
    title + preview/teaser. We capture whatever is available.

    Returns a dict with keys:
      title, author, author_handle, paragraphs, content, word_count, char_count,
      is_partial (True when content is likely truncated due to login wall)
    """
    lines = snapshot.split("\n")
    title: Optional[str] = None
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    paragraphs: List[str] = []

    # Patterns
    heading_re = re.compile(r'^-\s+heading\s+"(.+)"', re.IGNORECASE)
    text_re = re.compile(r'^-\s+text:\s+(.*)')
    link_re = re.compile(r'^-\s+link\s+"([^"]+)"')
    handle_re = re.compile(r'^@(\w+)$')

    # Strings to skip (navigation / boilerplate / empty)
    _SKIP_TEXTS = {
        "", "x", "home", "explore", "notifications", "messages", "grok",
        "profile", "more", "post", "log in", "sign up", "sign in",
        "already have an account?", "don't have an account?",
        "subscribe", "get the app", "help", "settings", "privacy policy",
        "terms of service", "cookie policy", "accessibility",
        "ads info", "more options", "follow", "following",
    }

    def _is_skip(text: str) -> bool:
        stripped = text.strip().lower()
        return stripped in _SKIP_TEXTS or len(stripped) < 2

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # ── Heading → title ────────────────────────────────────────────────
        m = heading_re.match(line)
        if m and not title:
            candidate = m.group(1).strip()
            if not _is_skip(candidate):
                title = candidate
            i += 1
            continue

        # ── text: lines ────────────────────────────────────────────────────
        m = text_re.match(line)
        if m:
            raw = m.group(1).strip()

            # Author @handle
            hm = handle_re.match(raw)
            if hm and not author_handle:
                author_handle = raw  # keep with @
                i += 1
                continue

            # Skip boilerplate
            if _is_skip(raw):
                i += 1
                continue

            # Skip short date-like strings immediately after author info
            # (e.g. "Feb 10, 2025") — we don't extract date for now, just skip
            if re.match(r'^[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}$', raw):
                i += 1
                continue

            # Author display name heuristic: single line, no spaces (but allow
            # names like "John Doe"), appears early before paragraphs, not a sentence
            if not author_name and not paragraphs and len(raw.split()) <= 4 and not raw.endswith("."):
                author_name = raw
                i += 1
                continue

            # Everything else is paragraph content
            paragraphs.append(raw)
            i += 1
            continue

        # ── Named links can sometimes be author name or article sub-heading ─
        m = link_re.match(line)
        if m:
            text = m.group(1).strip()
            hm = handle_re.match(text)
            if hm and not author_handle:
                author_handle = text
            elif not _is_skip(text) and not author_name and not paragraphs:
                author_name = text
            i += 1
            continue

        i += 1

    content = "\n\n".join(paragraphs)
    word_count = len(content.split()) if content else 0
    char_count = len(content)

    # Heuristic: if content is very short (< 100 chars), likely login wall
    is_partial = char_count < 100

    return {
        "title": title or "",
        "author": author_name or "",
        "author_handle": author_handle or "",
        "paragraphs": paragraphs,
        "content": content,
        "word_count": word_count,
        "char_count": char_count,
        "is_partial": is_partial,
    }


