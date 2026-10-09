"""Objective-aware performance aggregation with conservative attribution."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import pvariance
from typing import Any, Iterable

from .schema import MetricSnapshot, PublicationPerformance

LEARNING_VERSION = "1.0.0"
METRICS = ("reach", "impressions", "likes", "saves", "shares", "comments", "profile_visits",
           "story_completion", "link_clicks", "dms", "inquiries", "qualified_leads", "appointments", "conversions")
OBJECTIVE_WEIGHTS = {
    "awareness": {"reach": .35, "shares": .25, "profile_visits": .20, "saves": .12, "comments": .08},
    "engagement": {"saves": .28, "shares": .28, "comments": .20, "profile_visits": .14, "likes": .10},
    "education": {"saves": .35, "shares": .25, "story_completion": .20, "comments": .12, "profile_visits": .08},
    "conversion": {"conversions": .25, "appointments": .22, "qualified_leads": .20, "inquiries": .15, "dms": .10, "link_clicks": .08},
}
MIN_SAMPLES = {"EARLY_SIGNAL": 2, "MODERATE_CONFIDENCE": 5, "STRONG_SIGNAL": 12}


def publication_from_ledger(record: dict[str, Any], attribution: dict[str, Any] | None = None) -> PublicationPerformance:
    """Join immutable publication identity to a separate creative-attribution record."""
    attribution = attribution or {}
    publication_id = record.get("publication_identity") or record.get("publication_id")
    if not publication_id or not record.get("project_id"):
        raise ValueError("Ledger publication identity and project_id are required")
    return PublicationPerformance(
        publication_id=str(publication_id), project_id=str(record["project_id"]),
        platform=str(record.get("platform") or "unknown"), format=str(record.get("format") or record.get("surface") or "unknown"),
        objective=str(attribution.get("objective") or "engagement"), published_at=str(record.get("publication_timestamp") or record.get("published_at") or ""),
        post_package_id=record.get("package_id"), content_id=attribution.get("content_id"),
        asset_ids=list(attribution.get("asset_ids") or record.get("provenance_ids") or []),
        visual_direction_contract_id=attribution.get("visual_direction_contract_id"), pattern_ids=list(attribution.get("pattern_ids") or []),
        reci_opportunity_id=attribution.get("reci_opportunity_id"), campaign_id=attribution.get("campaign_id"),
        caption_version=attribution.get("caption_version") or record.get("caption_hash"), creative_family=str(attribution.get("creative_family") or "unknown"),
        composition_strategy=str(attribution.get("composition_strategy") or "unknown"), logo_prominence=str(attribution.get("logo_prominence") or "unknown"),
        information_density=str(attribution.get("information_density") or "unknown"), asset_type=str(attribution.get("asset_type") or "unknown"),
        headline_style=str(attribution.get("headline_style") or "unknown"), content_category=str(attribution.get("content_category") or "unknown"),
        carousel_length=attribution.get("carousel_length"), cta_type=str(attribution.get("cta_type") or "no_cta"),
        caption_structure=str(attribution.get("caption_structure") or "unknown"), story_structure=list(attribution.get("story_structure") or []),
        factual_safety=str(attribution.get("factual_safety") or "VERIFIED"), reci_attribution=dict(attribution.get("reci_attribution") or {}), snapshots=[])


def normalize_metrics(raw: dict[str, Any]) -> dict[str, float | int | None]:
    """Keep missing values null and reject negative/incompatible values."""
    result: dict[str, float | int | None] = {}
    for name in METRICS:
        value = raw.get(name)
        if value is None:
            result[name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"Invalid metric {name}: {value!r}")
        result[name] = value
    reach = result["reach"]
    for action in ("likes", "saves", "shares", "comments", "profile_visits", "link_clicks", "dms", "inquiries", "qualified_leads"):
        result[f"{action}_rate"] = None if reach in (None, 0) or result[action] is None else round(float(result[action]) / float(reach), 6)
    return result


def objective_aware_score(metrics: dict[str, Any], objective: str, baselines: dict[str, float] | None = None) -> float | None:
    """Return 0-100 relative score using only metrics meaningful to the objective."""
    weights = OBJECTIVE_WEIGHTS.get(objective.casefold(), OBJECTIVE_WEIGHTS["engagement"])
    values = []
    for metric, weight in weights.items():
        value = metrics.get(metric)
        if value is None:
            continue
        baseline = max(.000001, float((baselines or {}).get(metric, 1)))
        # Saturating relative utility prevents a viral result dominating learning.
        utility = 100 * (1 - math.exp(-max(0, float(value)) / baseline))
        values.append((utility, weight))
    if not values:
        return None
    return round(sum(v * w for v, w in values) / sum(w for _, w in values), 2)


class PerformanceLearningEngine:
    """Build advisory account and project learning without changing source truth."""

    def __init__(self, root: Path, *, now: datetime | None = None) -> None:
        self.root = root
        self.now = now or datetime.now(timezone.utc)

    def analyze(self, publications: Iterable[PublicationPerformance | dict[str, Any]], project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        records = [self._record(x) for x in publications]
        project_records = [x for x in records if x.project_id == project_id]
        evaluated = [self._evaluate(x, records) for x in project_records]
        usable = [x for x in evaluated if x["score"] is not None and not x["excluded_from_learning"]]
        account_evaluated = [self._evaluate(x, records) for x in records]
        account_usable = [x for x in account_evaluated if x["score"] is not None and not x["excluded_from_learning"]]
        pattern = self._aggregate(usable, "pattern_ids", multiple=True)
        category = self._aggregate(usable, "content_category")
        formats = self._aggregate(usable, "format")
        assets = self._aggregate(usable, "asset_type")
        ctas = self._aggregate(usable, "cta_type")
        fatigue = self._fatigue(usable)
        confidence = self._confidence(len(usable), [x["score"] for x in usable])
        status = "COLD_START" if not usable else "ACTIVE"
        review = {
            "schema_version": "1.0.0", "learning_version": LEARNING_VERSION, "project_id": project_id,
            "generated_at": self.now.isoformat(), "status": status, "publications_analyzed": len(project_records),
            "mature_publications": sum(x["maturity"] in {"MATURE", "FINALIZED"} for x in evaluated),
            "top_content": sorted(usable, key=lambda x: x["score"], reverse=True)[:5],
            "weak_content": sorted(usable, key=lambda x: x["score"])[:5], "pattern_performance": pattern,
            "category_performance": category, "format_performance": formats, "asset_type_performance": assets,
            "cta_performance": ctas, "audience_response": self._audience_response(category),
            "conversion_signals": self._conversion_signals(usable), "fatigue": fatigue,
            "creative_diversity_score": self._diversity(usable), "recommendations": self._recommendations(category, formats, fatigue),
            "confidence": confidence, "safety": {"advisory_only": True, "may_modify_project_truth": False, "causal_claims": False},
        }
        profile = self._profile(records, review, account_usable)
        return review, profile

    def write(self, publications: Iterable[PublicationPerformance | dict[str, Any]], project_id: str) -> tuple[Path, Path]:
        records = [self._record(x) for x in publications]
        review, profile = self.analyze(records, project_id)
        project_dir = self.root / "output" / "performance" / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        identity = {"schema_version": "1.0.0", "project_id": project_id, "publications": [x.to_dict() for x in records if x.project_id == project_id]}
        (project_dir / "publication-performance.json").write_text(json.dumps(identity, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        review_path = self.root / "output" / "performance-reviews" / f"{project_id}-performance-review.json"
        profile_path = self.root / "data" / "performance-learning" / "creative-learning-profile.json"
        review_path.parent.mkdir(parents=True, exist_ok=True); profile_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        history_path=self.root/"data"/"performance-history"/f"learning-{self.now.strftime('%Y%m%dT%H%M%SZ')}.json"
        history_path.parent.mkdir(parents=True,exist_ok=True)
        history_path.write_text(json.dumps({"learning_version":LEARNING_VERSION,"review":review,"profile":profile},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        return review_path, profile_path

    def _record(self, value: PublicationPerformance | dict[str, Any]) -> PublicationPerformance:
        if isinstance(value, PublicationPerformance): return value
        snapshots = [x if isinstance(x, MetricSnapshot) else MetricSnapshot(**x) for x in value.get("snapshots", [])]
        return PublicationPerformance(**{**value, "snapshots": snapshots})

    def _evaluate(self, record: PublicationPerformance, all_records: list[PublicationPerformance]) -> dict[str, Any]:
        snap = self._best_snapshot(record.snapshots)
        metrics = normalize_metrics(snap.metrics) if snap else normalize_metrics({})
        peers = [self._best_snapshot(x.snapshots) for x in all_records if x.platform == record.platform and x.format == record.format and x.objective == record.objective]
        baselines = {m: _median([normalize_metrics(x.metrics)[m] for x in peers if x and normalize_metrics(x.metrics)[m] is not None]) or 1 for m in METRICS}
        score = objective_aware_score(metrics, record.objective, baselines)
        outlier = bool(snap and (snap.outlier_reasons or self._statistical_outlier(record, all_records, score)))
        paid = snap.paid_status if snap else "unknown"
        unsafe = record.factual_safety not in {"VERIFIED", "SAFE", "APPROVED"}
        return {"publication_id": record.publication_id, "project_id": record.project_id, "platform": record.platform,
                "format": record.format, "objective": record.objective, "content_category": record.content_category,
                "asset_type": record.asset_type, "cta_type": record.cta_type, "pattern_ids": record.pattern_ids,
                "score": score, "metrics": metrics, "maturity": snap.maturity if snap else "EARLY",
                "paid_status": paid, "outlier": outlier, "factual_safety": record.factual_safety,
                "excluded_from_learning": outlier or unsafe or paid == "paid" or bool(snap and snap.freshness in {"STALE","INVALID"}),
                "recency_weight": self._recency_weight(record.published_at), "association_only": True}

    @staticmethod
    def _best_snapshot(items: list[MetricSnapshot]) -> MetricSnapshot | None:
        rank = {"1_hour": 1, "24_hour": 2, "72_hour": 3, "7_day": 4, "30_day": 5}
        return max(items, key=lambda x: rank.get(x.window, 0), default=None)

    def _aggregate(self, rows: list[dict[str, Any]], key: str, multiple: bool = False) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            values = row.get(key) or ["unknown"] if multiple else [row.get(key) or "unknown"]
            for value in values: groups[str(value)].append(row)
        result = []
        for name, group in sorted(groups.items()):
            scores = [x["score"] for x in group]; status = self._confidence(len(group), scores)
            weights=[x.get("recency_weight",1) for x in group]
            result.append({key[:-4] if key.endswith("_ids") else key: name, "usage_count": len(group),
                           "average_performance_score": round(sum(s*w for s,w in zip(scores,weights))/sum(weights), 2), "performance_confidence": status,
                           "association_only": True})
        return result

    def _recency_weight(self, published_at: str) -> float:
        try: published=datetime.fromisoformat(published_at.replace("Z","+00:00")); age=max(0,(self.now-published).days)
        except (TypeError,ValueError): return .5
        return round(.25 + .75 * math.exp(-age / 180), 4)

    def _confidence(self, count: int, scores: list[float]) -> str:
        if count < MIN_SAMPLES["EARLY_SIGNAL"]: return "INSUFFICIENT_DATA"
        variance = pvariance(scores) if len(scores) > 1 else 0
        if count >= MIN_SAMPLES["STRONG_SIGNAL"] and variance <= 225: return "STRONG_SIGNAL"
        if count >= MIN_SAMPLES["MODERATE_CONFIDENCE"] and variance <= 625: return "MODERATE_CONFIDENCE"
        return "EARLY_SIGNAL"

    def _statistical_outlier(self, record: PublicationPerformance, records: list[PublicationPerformance], score: float | None) -> bool:
        if score is None: return False
        peer_scores = []
        for other in records:
            if other is record or other.platform != record.platform or other.format != record.format: continue
            snap = self._best_snapshot(other.snapshots)
            if snap:
                value = objective_aware_score(normalize_metrics(snap.metrics), other.objective)
                if value is not None: peer_scores.append(value)
        return len(peer_scores) >= 5 and score > (_median(peer_scores) or 0) * 2.5

    @staticmethod
    def _fatigue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[float]] = defaultdict(list)
        for x in rows:
            for pattern in x["pattern_ids"]: groups[pattern].append(x["score"])
        return [{"pattern_id": k, "status": "FATIGUE_RISK", "association_only": True} for k,v in groups.items() if len(v)>=4 and v[-1] < v[0]*.75 and all(a>=b for a,b in zip(v,v[1:]))]

    @staticmethod
    def _diversity(rows: list[dict[str, Any]]) -> float:
        if not rows: return 0.0
        fields=("content_category","asset_type","format","cta_type")
        return round(100*sum(min(1,len({x[f] for x in rows})/min(4,len(rows))) for f in fields)/len(fields),2)

    @staticmethod
    def _audience_response(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"content_category": x["content_category"], "account_specific": True, "performance_score": x["average_performance_score"], "confidence": x["performance_confidence"]} for x in categories]

    @staticmethod
    def _conversion_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"publication_id":x["publication_id"], "qualified_leads":x["metrics"].get("qualified_leads"), "inquiries":x["metrics"].get("inquiries"), "attribution":"UNATTRIBUTED"} for x in rows if any(x["metrics"].get(k) for k in ("qualified_leads","inquiries","appointments","conversions"))]

    @staticmethod
    def _recommendations(categories, formats, fatigue):
        ranked=sorted(categories,key=lambda x:x["average_performance_score"],reverse=True)
        result=[{"type":"category","value":x["content_category"],"strength":x["performance_confidence"],"advisory":True} for x in ranked[:3] if x["performance_confidence"]!="INSUFFICIENT_DATA"]
        result.extend({"type":"fatigue","value":x["pattern_id"],"strength":"CAUTION","advisory":True} for x in fatigue)
        return result

    def _profile(self, all_records: list[PublicationPerformance], review: dict[str, Any], account_rows: list[dict[str, Any]]) -> dict[str, Any]:
        projects=sorted({x.project_id for x in all_records}); count=sum(len(x.snapshots)>0 for x in all_records)
        return {"schema_version":"1.0.0","learning_version":LEARNING_VERSION,"updated_at":self.now.isoformat(),
                "data_window":{"start":min((x.published_at for x in all_records),default=None),"end":max((x.published_at for x in all_records),default=None)},
                "publication_count":count,"project_count":len(projects),"status":"COLD_START" if count==0 else "ACTIVE",
                "account_effectiveness":{"scope":"ACCOUNT","category_performance":self._aggregate(account_rows,"content_category"),"format_performance":self._aggregate(account_rows,"format"),"pattern_performance":self._aggregate(account_rows,"pattern_ids",multiple=True),"cta_performance":self._aggregate(account_rows,"cta_type")},
                "project_effectiveness":{review["project_id"]:{"category_performance":review["category_performance"],"confidence":review["confidence"]}},
                "planning_advice":{"fatigue":review["fatigue"],"recommendations":review["recommendations"],"exploration_modes":["PROVEN","BALANCED","EXPERIMENTAL"]},
                "safety":{"advisory_only":True,"factual_integrity_precedence":True,"unsupported_content_never_promoted":True}}


def _median(values: list[float | int]) -> float | None:
    values=sorted(float(x) for x in values)
    if not values:return None
    middle=len(values)//2
    return values[middle] if len(values)%2 else (values[middle-1]+values[middle])/2
