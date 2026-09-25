"""Backend protocol.

Every backend implements the same surface; capabilities it lacks raise
``NotSupported`` so the router can fall through to the next backend.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..exceptions import NotSupported
from ..models import Article, Profile, Reply, Tweet


class Backend:
    """Base backend. Subclasses override what they support."""

    name = "base"

    def available(self) -> bool:
        """Cheap reachability check. Never raises."""
        return False

    # ── capabilities ─────────────────────────────────────────────────────
    def fetch_tweet(self, username: str, tweet_id: str) -> Dict[str, Any]:
        raise NotSupported(f"{self.name}: fetch_tweet")

    def fetch_timeline(self, username: str, limit: int = 20) -> List[Tweet]:
        raise NotSupported(f"{self.name}: fetch_timeline")

    def fetch_replies(self, username: str, tweet_id: str) -> List[Reply]:
        raise NotSupported(f"{self.name}: fetch_replies")

    def search(self, query: str, limit: int = 20) -> List[Tweet]:
        raise NotSupported(f"{self.name}: search")

    def fetch_list(self, list_id: str, limit: int = 20) -> List[Tweet]:
        raise NotSupported(f"{self.name}: fetch_list")

    def fetch_article(self, article_id: str) -> Article:
        raise NotSupported(f"{self.name}: fetch_article")

    def fetch_user_info(self, username: str) -> Profile:
        raise NotSupported(f"{self.name}: fetch_user_info")
