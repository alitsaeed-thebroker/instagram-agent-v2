"""Validated JSON contract for campaign planning artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


IMAGE_ORIENTATIONS = {"Square", "Portrait", "Landscape"}
SUGGESTED_PLATFORMS = {"Instagram Feed", "Instagram Carousel", "Instagram Story", "Facebook", "LinkedIn", "Website"}


@dataclass
class CampaignPost:
    post_number: int
    title: str
    content_goal: str
    visual_concept: str
    image_orientation: str
    suggested_platform: str
    priority: str


@dataclass
class Campaign:
    campaign_name: str
    objective: str
    target_audience: str
    marketing_message: str
    emotional_trigger: str
    priority: str
    recommended_number_of_posts: int
    posts: list[CampaignPost] = field(default_factory=list)


@dataclass
class CampaignPlan:
    """A reusable content plan derived from one marketing strategy."""

    campaigns: list[Campaign] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.campaigns, list):
            return ["campaigns must be a list of objects"]
        for campaign_index, campaign in enumerate(self.campaigns):
            prefix = f"campaigns[{campaign_index}]"
            if not isinstance(campaign, Campaign):
                errors.append(f"{prefix} must be an object")
                continue
            if not all(isinstance(getattr(campaign, name), str) for name in _CAMPAIGN_STRING_FIELDS):
                errors.append(f"{prefix} text fields must be strings")
            if not isinstance(campaign.recommended_number_of_posts, int) or campaign.recommended_number_of_posts < 0:
                errors.append(f"{prefix}.recommended_number_of_posts must be a non-negative integer")
            if not isinstance(campaign.posts, list):
                errors.append(f"{prefix}.posts must be a list of objects")
                continue
            if len(campaign.posts) != campaign.recommended_number_of_posts:
                errors.append(f"{prefix}.posts must match recommended_number_of_posts")
            for post_index, post in enumerate(campaign.posts):
                post_prefix = f"{prefix}.posts[{post_index}]"
                if not isinstance(post, CampaignPost):
                    errors.append(f"{post_prefix} must be an object")
                    continue
                if not isinstance(post.post_number, int) or post.post_number < 1:
                    errors.append(f"{post_prefix}.post_number must be a positive integer")
                if not all(isinstance(getattr(post, name), str) for name in _POST_STRING_FIELDS):
                    errors.append(f"{post_prefix} text fields must be strings")
                if post.image_orientation not in IMAGE_ORIENTATIONS:
                    errors.append(f"{post_prefix}.image_orientation must be Square, Portrait, or Landscape")
                if post.suggested_platform not in SUGGESTED_PLATFORMS:
                    errors.append(f"{post_prefix}.suggested_platform is not supported")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CampaignPlan":
        if not isinstance(data, dict) or set(data) != {"campaigns"}:
            raise ValueError("Campaign plan JSON must contain only a campaigns field")
        raw_campaigns = data["campaigns"]
        if not isinstance(raw_campaigns, list):
            raise ValueError("campaigns must be a list of objects")
        try:
            campaigns = []
            for item in raw_campaigns:
                if not isinstance(item, dict) or set(item) != set(_CAMPAIGN_FIELDS):
                    raise ValueError("Campaign plan JSON has unexpected or missing campaign fields")
                posts = item["posts"]
                if not isinstance(posts, list) or any(not isinstance(post, dict) or set(post) != set(_POST_FIELDS) for post in posts):
                    raise ValueError("Campaign plan JSON has unexpected or missing post fields")
                campaigns.append(Campaign(
                    **{name: item[name] for name in _CAMPAIGN_FIELDS if name != "posts"},
                    posts=[CampaignPost(**post) for post in posts],
                ))
            plan = cls(campaigns=campaigns)
        except (KeyError, TypeError) as error:
            raise ValueError("Campaign plan JSON has an invalid structure") from error
        errors = plan.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return plan

    @classmethod
    def from_json(cls, payload: str) -> "CampaignPlan":
        try:
            return cls.from_dict(json.loads(payload))
        except json.JSONDecodeError as error:
            raise ValueError("Campaign plan JSON is invalid") from error


_CAMPAIGN_FIELDS = tuple(Campaign.__dataclass_fields__)
_POST_FIELDS = tuple(CampaignPost.__dataclass_fields__)
_CAMPAIGN_STRING_FIELDS = ("campaign_name", "objective", "target_audience", "marketing_message", "emotional_trigger", "priority")
_POST_STRING_FIELDS = ("title", "content_goal", "visual_concept", "image_orientation", "suggested_platform", "priority")
