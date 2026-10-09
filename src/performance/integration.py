"""Narrow advisory views for downstream departments."""
from __future__ import annotations
from copy import deepcopy
from typing import Any


def campaign_planner_context(profile: dict[str, Any]) -> dict[str, Any]:
    """Expose planning signals, never raw metrics or source-truth mutations."""
    return {"learning_version": profile.get("learning_version", "unavailable"), "status": profile.get("status", "COLD_START"),
            "category_performance": deepcopy((profile.get("account_effectiveness") or {}).get("category_performance", [])),
            "format_performance": deepcopy((profile.get("account_effectiveness") or {}).get("format_performance", [])),
            "fatigue": deepcopy((profile.get("planning_advice") or {}).get("fatigue", [])),
            "recommendations": deepcopy((profile.get("planning_advice") or {}).get("recommendations", [])), "advisory_only": True}


def content_planner_context(profile: dict[str, Any]) -> dict[str, Any]:
    account=profile.get("account_effectiveness") or {}
    return {"learning_version":profile.get("learning_version","unavailable"),"status":profile.get("status","COLD_START"),
            "opportunity_context":deepcopy(account.get("category_performance",[])),"cta_performance":deepcopy(account.get("cta_performance",[])),
            "format_preference":deepcopy(account.get("format_performance",[])),"advisory_only":True}


def visual_art_director_context(profile: dict[str, Any]) -> dict[str, Any]:
    """VAD receives qualitative summaries only and retains final authority."""
    recommendations=(profile.get("planning_advice") or {}).get("recommendations",[])
    summaries=[f"{x.get('value')} has a {str(x.get('strength','')).lower().replace('_',' ')} account-level association." for x in recommendations if x.get("type")=="category"]
    return {"learning_version":profile.get("learning_version","unavailable"),"contextual_insights":summaries,
            "raw_metrics_included":False,"advisory_only":True,"final_creative_authority":"VISUAL_ART_DIRECTOR"}


def library_effectiveness_view(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return local overlays; canonical pattern quality is intentionally untouched."""
    patterns=(profile.get("account_effectiveness") or {}).get("pattern_performance",[])
    return {str(x.get("pattern_id")):{"account_performance":x.get("average_performance_score"),"usage_count":x.get("usage_count",0),
            "performance_confidence":x.get("performance_confidence"),"association_only":True} for x in patterns if x.get("pattern_id")}
