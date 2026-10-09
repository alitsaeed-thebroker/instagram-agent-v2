"""Deterministic source-grounded copy and semantic quality checks."""

from __future__ import annotations
import re
from typing import Any

GENERIC_PHRASES = ("discover the project", "learn more", "explore more", "luxury living", "modern lifestyle", "your dream home")


def assess_marketing_comprehension(*, text: str, project_name: str = "", developer_name: str = "",
                                   visual_category: str = "unknown", verified_facts: list[Any] | None = None) -> dict[str, Any]:
    normalized=_norm(text); facts=verified_facts or []; warnings=[]
    generic_hits=[x for x in GENERIC_PHRASES if x in normalized]
    informative_tokens=[x for x in normalized.split() if len(x)>3 and x not in set("discover project learn more explore luxury living modern lifestyle your dream home".split())]
    if generic_hits and len(informative_tokens)<8: warnings.append("creative message is mostly generic marketing language")
    if not project_name or _norm(project_name) not in normalized: warnings.append("project is not clearly identified")
    if visual_category in {"", "unknown"}: warnings.append("visual category is unknown")
    if not facts: warnings.append("no verified project facts support the message")
    score=max(0,100-25*len(warnings))
    return {"score":score,"status":"pass" if score>=75 else "fail","warnings":warnings,
        "generic_phrases":generic_hits,"project_identified":bool(project_name and _norm(project_name) in normalized),
        "developer_identified":bool(developer_name and _norm(developer_name) in normalized),"source_grounded":bool(facts)}


def duplicate_copy_fields(title: str, subtitle: str = "", body: str = "") -> list[str]:
    values=[("title",title),("subtitle",subtitle),("body",body)];errors=[]
    for i,(a,av) in enumerate(values):
        for b,bv in values[i+1:]:
            if av.strip() and _norm(av)==_norm(bv): errors.append(f"duplicate {a}/{b} copy")
    if re.search(r"\b(.{2,40}?)\s*[—–:\-|]\s*\1\b", " ".join(x[1] for x in values), re.I): errors.append("repeated copy segment")
    return errors


def semantic_match(content_category: str, visual_category: str) -> bool:
    expected={"villa_exterior":{"villa_exterior"},"villa_interior":{"villa_interior"},"site_plan":{"site_plan"},
        "masterplan":{"masterplan"},"villa_layout":{"villa_layout","floor_plan"},"floor_plan":{"floor_plan","villa_layout"},
        "community_services":{"community_services","amenities"},"greenery_landscape":{"greenery_landscape"},
        "amenities":{"amenities","clubhouse","swimming_pool"},"location":{"location_map"},"location_map":{"location_map"}}
    key=_norm(content_category).replace(" ","_");return visual_category in expected.get(key,{visual_category}) and visual_category!="unknown"


def _norm(value: str) -> str:return re.sub(r"\s+"," ",re.sub(r"[^\w\s]"," ",str(value).casefold())).strip()
