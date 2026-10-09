"""Structural boundary between internal planning data and renderable copy."""
from __future__ import annotations
import re
from typing import Any

PUBLIC_FIELDS = ("project_name", "headline", "subheadline", "cta", "website")
INTERNAL_COPY_PATTERNS = re.compile(
    r"\b(?:[^\n:]+:\s*(?:awareness|consideration|conversion)\b|approved\s+assets?|single_feed_post|content\s+idea|production\s+item|visual\s+direction\s+contract|"
    r"source\s+asset|present\s+[12]\b|only\s+the\s+verified\s+facts\s+listed|asset\(s\)|planning|processor|vdc|pi1)\b",
    re.I,
)


def public_copy(value: dict[str, Any]) -> dict[str, str | None]:
    """Return only explicitly public fields; never infer copy from planner prose."""
    explicit=value.get("public_copy") if isinstance(value.get("public_copy"),dict) else {}
    result={name:(str(explicit[name]).strip() if explicit.get(name) not in {None,""} else None) for name in PUBLIC_FIELDS}
    errors=validate_public_copy(result)
    if errors: raise ValueError("Public copy rejected: "+"; ".join(errors))
    return result


def validate_public_copy(value: dict[str, Any]) -> list[str]:
    errors=[]
    unknown=set(value)-set(PUBLIC_FIELDS)
    if unknown:errors.append("non-public fields present: "+", ".join(sorted(unknown)))
    for name in PUBLIC_FIELDS:
        text=str(value.get(name) or "").strip()
        if INTERNAL_COPY_PATTERNS.search(text):errors.append(f"{name} contains internal production language")
    return errors
