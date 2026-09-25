"""x-tweet-fetcher — fetch X/Twitter tweets without login or API keys.

Programmatic usage:

    from xtf import Router
    router = Router()                       # backend="auto"
    tweet   = router.fetch_tweet("user", "1234567890")
    tweets  = router.fetch_timeline("user", limit=20)
    replies = router.fetch_replies("user", "1234567890")
    results = router.search("openclaw", limit=10)
"""
from .exceptions import (
    AllBackendsFailed,
    BackendUnavailable,
    InvalidInput,
    NotFound,
    NotSupported,
    RateLimited,
    UpstreamDown,
    XtfError,
)
from .models import Article, Profile, Reply, Tweet
from .router import Router

__version__ = "3.1.0"

__all__ = [
    "Router", "Tweet", "Reply", "Profile", "Article",
    "XtfError", "InvalidInput", "NotFound", "RateLimited",
    "UpstreamDown", "BackendUnavailable", "NotSupported", "AllBackendsFailed",
    "__version__",
]
