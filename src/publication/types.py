"""One semantic vocabulary for publication intent across all departments."""
from __future__ import annotations
from enum import Enum
from typing import Any


class PublicationType(str, Enum):
    SINGLE_POST = "single_post"
    CAROUSEL = "carousel"
    STORY = "story"
    REEL = "reel"


_ALIASES = {
    "single_post": PublicationType.SINGLE_POST, "single feed post": PublicationType.SINGLE_POST,
    "single_feed_post": PublicationType.SINGLE_POST, "instagram feed": PublicationType.SINGLE_POST,
    "carousel": PublicationType.CAROUSEL, "instagram carousel": PublicationType.CAROUSEL,
    "story": PublicationType.STORY, "instagram story": PublicationType.STORY, "instagram_story": PublicationType.STORY,
    "reel": PublicationType.REEL, "instagram reel": PublicationType.REEL, "instagram_reel": PublicationType.REEL,
}


def normalize_publication_type(value: Any, *, strict: bool = True) -> str | None:
    key = " ".join(str(value or "").strip().casefold().replace("-", " ").split())
    result = _ALIASES.get(key) or _ALIASES.get(key.replace(" ", "_"))
    if result is None and strict:
        raise ValueError(f"Ambiguous or unsupported publication type: {value!r}")
    return result.value if result else None


def publication_intent(kind: Any, *, platform: str = "instagram", media_type: str = "image") -> dict[str, Any]:
    canonical = normalize_publication_type(kind)
    if canonical == PublicationType.STORY.value:
        if platform.casefold() != "instagram" or media_type != "image": raise ValueError("V1 Story requires an Instagram image target")
        return {"platform":"instagram","publication_type":"story","media_type":"image","width":1080,"height":1920,"aspect_ratio":"9:16"}
    dimensions=(1080,1350,"4:5")
    return {"platform":platform.casefold(),"publication_type":canonical,"media_type":media_type,"width":dimensions[0],"height":dimensions[1],"aspect_ratio":dimensions[2]}
