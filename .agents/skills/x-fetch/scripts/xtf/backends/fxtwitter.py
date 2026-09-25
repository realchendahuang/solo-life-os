"""FxTwitter backend — single tweets and user profiles, zero dependencies.

Output of ``fetch_tweet`` reproduces the v1 ``tweet`` dict byte-for-byte
(including the article full-text reconstruction from Draft.js blocks).
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from .. import http
from ..exceptions import NotFound, UpstreamDown, XtfError
from ..models import Profile
from ..parsers.fxtwitter_json import extract_media
from .base import Backend

API = "https://api.fxtwitter.com"

# local patch (X-Tiller): metric keys the upstream tweet payload may carry,
# mapped to the keys normalize_tweet_json emits. Used for metrics_present.
_METRIC_KEY_MAP = (
    ("views", "views"),
    ("likes", "likes"),
    ("retweets", "retweets"),
    ("bookmarks", "bookmarks"),
    ("replies", "replies_count"),
)

# local patch (X-Tiller): never trust a mirror response for a different tweet.
_ID_KEYS = ("id", "id_str", "tweet_id")


def _verify_tweet_identity(payload: Dict[str, Any], username: str, tweet_id: str) -> None:
    """Raise UpstreamDown unless the payload is the requested tweet.

    A cached, redirected, or wrong mirror response must never be archived
    under the requested id (the ledger dedupes on it).
    """
    returned_id = next(
        (str(payload[k]) for k in _ID_KEYS if payload.get(k) not in (None, "")), ""
    )
    raw_author = payload.get("author")
    author: Dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
    returned_handle = str(author.get("screen_name", "")).lstrip("@")
    if returned_id != str(tweet_id):
        raise UpstreamDown(
            "FxTwitter payload identity mismatch: returned tweet id "
            f"{returned_id or 'unknown'} for requested {tweet_id}"
        )
    if returned_handle.casefold() != username.lstrip("@").casefold():
        raise UpstreamDown(
            "FxTwitter payload identity mismatch: returned author "
            f"@{returned_handle or 'unknown'} for requested @{username.lstrip('@')}"
        )


def _reconstruct_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild article full_text (with inline images) from Draft.js blocks."""
    article_data: Dict[str, Any] = {
        "title": article.get("title", ""),
        "preview_text": article.get("preview_text", ""),
        "created_at": article.get("created_at", ""),
    }
    content = article.get("content", {})
    blocks = content.get("blocks", [])
    cover = article.get("cover_media", {})
    media_entities = article.get("media_entities", [])

    if blocks:
        media_id_to_url: Dict[str, str] = {}
        if cover:
            cover_url = cover.get("media_info", {}).get("original_img_url")
            cover_id = cover.get("media_id")
            if cover_url and cover_id:
                media_id_to_url[str(cover_id)] = cover_url
        for me in media_entities:
            mid = str(me.get("media_id", ""))
            murl = me.get("media_info", {}).get("original_img_url", "")
            if mid and murl:
                media_id_to_url[mid] = murl

        entity_map = content.get("entityMap") or {}
        key_to_url: Dict[str, str] = {}
        if isinstance(entity_map, dict):
            for e_key, e_val in entity_map.items():
                if isinstance(e_val, dict) and e_val.get("type") == "MEDIA":
                    for mi in e_val.get("data", {}).get("mediaItems", []):
                        if isinstance(mi, dict):
                            mid = str(mi.get("mediaId", ""))
                            if mid in media_id_to_url:
                                key_to_url[str(e_key)] = media_id_to_url[mid]
        elif isinstance(entity_map, list):
            for e in entity_map:
                if not isinstance(e, dict):
                    continue
                v = e.get("value", {})
                k = e.get("key")
                if isinstance(v, dict) and v.get("type") == "MEDIA" and k is not None:
                    for mi in v.get("data", {}).get("mediaItems", []):
                        if isinstance(mi, dict):
                            mid = str(mi.get("mediaId", ""))
                            if mid in media_id_to_url:
                                key_to_url[str(k)] = media_id_to_url[mid]

        atomic_media: Dict[int, str] = {}
        for bi, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "atomic":
                for r in b.get("entityRanges", []):
                    if not isinstance(r, dict):
                        continue
                    ek = r.get("key")
                    if ek is not None and str(ek) in key_to_url:
                        atomic_media[bi] = key_to_url[str(ek)]

        text_parts: List[str] = []
        for bi, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            btext = b.get("text", "")
            if btype == "atomic":
                if bi in atomic_media:
                    img_url = atomic_media[bi]
                    if (
                        isinstance(img_url, str)
                        and img_url.startswith(("https://", "http://"))
                        and ")" not in img_url
                        and "\n" not in img_url
                        and "\r" not in img_url
                    ):
                        text_parts.append(f"![]({img_url})")
                elif btext:
                    text_parts.append(btext)
            elif btext:
                text_parts.append(btext)
        full_text = "\n\n".join(text_parts)
        article_data["full_text"] = full_text
        article_data["word_count"] = len(full_text.split())
        article_data["char_count"] = len(full_text)

    article_images = []
    if cover:
        cover_url = cover.get("media_info", {}).get("original_img_url")
        if cover_url:
            article_images.append({"type": "cover", "url": cover_url})
    for entity in media_entities:
        img_url = entity.get("media_info", {}).get("original_img_url")
        if img_url:
            article_images.append({"type": "image", "url": img_url})
    if article_images:
        article_data["images"] = article_images
        article_data["image_count"] = len(article_images)

    return article_data


def normalize_tweet_json(tweet: Dict[str, Any]) -> Dict[str, Any]:
    """FxTwitter tweet object -> v1-compatible tweet dict. Pure."""
    tweet_data: Dict[str, Any] = {
        "text": tweet.get("text", ""),
        "author": tweet.get("author", {}).get("name", ""),
        "screen_name": tweet.get("author", {}).get("screen_name", ""),
        "likes": tweet.get("likes", 0),
        "retweets": tweet.get("retweets", 0),
        "bookmarks": tweet.get("bookmarks", 0),
        "views": tweet.get("views", 0),
        "replies_count": tweet.get("replies", 0),
        "created_at": tweet.get("created_at", ""),
        "is_note_tweet": tweet.get("is_note_tweet", False),
        "lang": tweet.get("lang", ""),
    }
    # local patch (X-Tiller): record which metrics upstream actually reported,
    # so a real 0 can be told apart from a missing value. Additive only.
    tweet_data["metrics_present"] = sorted(
        {
            emitted
            for raw_key, emitted in _METRIC_KEY_MAP
            if isinstance(tweet.get(raw_key), (int, float))
            and not isinstance(tweet.get(raw_key), bool)
        }
    )

    media = extract_media(tweet)
    if media:
        tweet_data["media"] = media

    if tweet.get("quote"):
        qt = tweet["quote"]
        tweet_data["quote"] = {
            "text": qt.get("text", ""),
            "author": qt.get("author", {}).get("name", ""),
            "screen_name": qt.get("author", {}).get("screen_name", ""),
            "likes": qt.get("likes", 0),
            "retweets": qt.get("retweets", 0),
            "views": qt.get("views", 0),
        }
        quote_media = extract_media(qt)
        if quote_media:
            tweet_data["quote"]["media"] = quote_media

    article = tweet.get("article")
    if article:
        tweet_data["article"] = _reconstruct_article(article)
        tweet_data["is_article"] = True
    else:
        tweet_data["is_article"] = False

    return tweet_data


class FxTwitterBackend(Backend):
    name = "fxtwitter"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def available(self) -> bool:
        return True  # public API; failures surface per-call

    def fetch_tweet(self, username: str, tweet_id: str) -> Dict[str, Any]:
        data = http.get_json(
            f"{API}/{username}/status/{tweet_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=self.timeout,
        )
        code = data.get("code")
        if code == 404:
            raise NotFound(f"tweet {username}/{tweet_id} not found")
        if code != 200:
            raise UpstreamDown(
                f"FxTwitter returned code {code}: {data.get('message', 'Unknown')}"
            )
        payload = data.get("tweet")
        if not isinstance(payload, dict):
            raise UpstreamDown(
                f"FxTwitter returned no tweet object for {username}/{tweet_id}"
            )
        # local patch (X-Tiller): reject mismatched mirror payloads outright.
        _verify_tweet_identity(payload, username, tweet_id)
        return normalize_tweet_json(payload)

    def fetch_user_info(self, username: str) -> Profile:
        data = http.get_json(f"{API}/{username}", timeout=10)
        u = data.get("user", {})
        if not u:
            raise NotFound(f"user @{username} not found")
        return Profile(
            username=u.get("screen_name", username),
            display_name=u.get("name", ""),
            bio=u.get("description", ""),
            tweets_count=u.get("tweets", 0),
            followers=u.get("followers", 0),
            following=u.get("following", 0),
            joined=u.get("joined", ""),
        )

    def fetch_user_info_dict(self, username: str) -> Dict[str, Any]:
        """v1-compatible extended profile dict (includes avatar/banner/etc)."""
        data = http.get_json(f"{API}/{username}", timeout=10)
        u = data.get("user", {})
        if not u:
            raise NotFound(f"user @{username} not found")
        return {
            "username": u.get("screen_name", username),
            "display_name": u.get("name", ""),
            "bio": u.get("description", ""),
            "tweets_count": u.get("tweets", 0),
            "followers": u.get("followers", 0),
            "following": u.get("following", 0),
            "joined": u.get("joined", ""),
            "avatar": u.get("avatar_url", ""),
            "banner": u.get("banner_url", ""),
            "likes": u.get("likes", 0),
            "website": u.get("website", ""),
        }


def supplement_views(tweets: List[Dict], max_supplement: int = 50) -> Dict[str, int]:
    """Fill missing view counts via FxTwitter. Best-effort, never raises.

    local patch (X-Tiller): returns the real outcome
    ``{"requested": N, "filled": M, "failed": F, "skipped": S}`` instead of the
    list. Only views==0 items with an author and id are requested; N is capped
    at max_supplement, and the caller must report M, not an unconditional True.
    """
    stats = {"requested": 0, "filled": 0, "failed": 0, "skipped": 0}
    for tw in tweets[:max_supplement]:
        if tw.get("views", 0) != 0:
            continue
        author = tw.get("author", "")
        if not author or not author.startswith("@"):
            stats["skipped"] += 1
            continue
        username = author.lstrip("@")
        tweet_id = tw.get("tweet_id") or tw.get("id")
        if not tweet_id:
            stats["skipped"] += 1
            continue
        stats["requested"] += 1
        try:
            data = http.get_json(
                f"{API}/{username}/status/{tweet_id}", timeout=5, retries=0
            )
            raw_tweet = data.get("tweet", {})
            upstream_views = raw_tweet.get("views")
            if upstream_views:
                tw["views"] = upstream_views
                tw.pop("views_unknown", None)
                stats["filled"] += 1
                print(f"[views] {username}/{str(tweet_id)[:8]}... -> {upstream_views}",
                      file=sys.stderr)
            elif isinstance(upstream_views, (int, float)) and not isinstance(
                upstream_views, bool
            ):
                # local patch (X-Tiller): upstream reported a real 0 (measured).
                tw["views_unknown"] = False
            else:
                # local patch (X-Tiller): absent upstream views are unknown, not 0.
                tw["views_unknown"] = True
        except XtfError:
            stats["failed"] += 1
    return stats
