"""Offline quality evaluation for generated project knowledge JSON artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from typing import Any

from src.utils.config import KNOWLEDGE_OUTPUT_DIRECTORY
from src.knowledge.source_recovery import recover_project

EVALUATOR_VERSION = "Knowledge Evaluator v4-read-only"


@dataclass
class KnowledgeEvaluation:
    """Serializable quality report for a single knowledge artifact."""

    evaluator_version: str
    project: str
    json_validity: dict[str, Any]
    category_scores: dict[str, float]
    overall_score: float
    completeness_percentage: float
    completed_fields: int
    total_fields: int
    missing_fields: list[str]
    warnings: list[str]
    strengths: list[str]
    recommendations: list[str]
    source_utilization_score: float = 100.0
    project_completeness_score: float = 100.0
    source_coverage: dict[str, Any] = field(default_factory=dict)
    recovery_requests: list[dict[str, Any]] = field(default_factory=list)
    recovered_atomic_facts: list[dict[str, Any]] = field(default_factory=list)
    information_density: dict[str, int] = field(default_factory=dict)
    missing_knowledge: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeEvaluator:
    """Measure completeness and quality of knowledge without external services."""

    def evaluate_file(self, knowledge_path: Path) -> KnowledgeEvaluation:
        """Evaluate a JSON file, returning an invalid-JSON report when needed."""
        project = knowledge_path.stem
        try:
            data = json.loads(knowledge_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return self._invalid_json_report(project, str(error))
        evaluation=self.evaluate_data(data, project)
        recovery=recover_project(knowledge_path,data,max_passes=0)
        evaluation.source_utilization_score=recovery["source_utilization_score"];evaluation.project_completeness_score=recovery["project_completeness_score"]
        evaluation.source_coverage={"page_coverage":recovery["page_coverage"],"category_counts":recovery["category_counts"],"category_scores":recovery["category_scores"],"applicable_categories":recovery["applicable_categories"],"recovery_policy":recovery["recovery_policy"],"unreadable_sources":recovery["unreadable_sources"]}
        evaluation.recovery_requests=recovery["recovery_requests"];evaluation.recovered_atomic_facts=recovery["recovered_atomic_facts"];evaluation.information_density=recovery["information_density"];evaluation.missing_knowledge=recovery["missing_knowledge"]
        return evaluation

    def evaluate_data(self, data: Any, project_name: str = "Unknown Project") -> KnowledgeEvaluation:
        """Evaluate a decoded JSON object against the current knowledge contract."""
        if not isinstance(data, dict):
            return self._invalid_json_report(project_name, "Top-level JSON value must be an object")

        project = _mapping(data.get("project"))
        pricing = _mapping(data.get("pricing"))
        architecture = _mapping(data.get("architecture"))
        marketing = _mapping(data.get("marketing"))
        units = _list_of_mappings(data.get("units"))
        amenities = data.get("amenities", [])

        field_scores = {
            "project.name": _meaningful_score(project.get("name")),
            "project.developer": _meaningful_score(project.get("developer")),
            "project.location": _meaningful_score(project.get("location")),
            "project.description": _meaningful_score(project.get("description")),
            "pricing.currency": _meaningful_score(pricing.get("currency")),
            "pricing.starting_price": _meaningful_score(pricing.get("starting_price")),
            "architecture.style": _meaningful_score(architecture.get("style")),
            "architecture.materials": _list_score(architecture.get("materials"), target_count=2),
            "architecture.design_features": _list_score(architecture.get("design_features"), target_count=2),
            "marketing.target_audience": _list_score(marketing.get("target_audience"), target_count=2),
            "marketing.selling_points": _list_score(marketing.get("selling_points"), target_count=2),
        }

        unit_scores = {
            "unit names": _coverage(units, "name"),
            "bedrooms": _coverage(units, "bedrooms"),
            "bathrooms": _coverage(units, "bathrooms"),
            "areas": _coverage(units, "area_sqm"),
        }
        for name, score in unit_scores.items():
            field_scores[f"units.{name}"] = score

        valid_amenities = amenities if isinstance(amenities, list) else []
        empty_amenities = [item for item in valid_amenities if not _meaningful_text(item)]
        normalized = [item.strip().casefold() for item in valid_amenities if _meaningful_text(item)]
        duplicate_amenities = sorted({item for item in normalized if normalized.count(item) > 1})
        amenity_count_score = min(len(set(normalized)), 3) / 3 * 60
        amenities_score = amenity_count_score
        if not duplicate_amenities:
            amenities_score += 20.0
        if not empty_amenities:
            amenities_score += 20.0
        field_scores["amenities"] = min(len(set(normalized)), 3) / 3

        project_score = _average(field_scores, [
            "project.name", "project.developer", "project.location", "project.description",
        ]) * 100
        pricing_score = _average(field_scores, ["pricing.currency", "pricing.starting_price"]) * 100
        units_score = sum(unit_scores.values()) / len(unit_scores) * 100
        architecture_score = _average(field_scores, [
            "architecture.style", "architecture.materials", "architecture.design_features",
        ]) * 100
        marketing_score = _average(field_scores, [
            "marketing.target_audience", "marketing.selling_points",
        ]) * 100
        category_scores = {
            "project_information": round(project_score, 1),
            "pricing": round(pricing_score, 1),
            "units": round(units_score, 1),
            "amenities": round(amenities_score, 1),
            "architecture": round(architecture_score, 1),
            "marketing": round(marketing_score, 1),
        }
        overall_score = sum(
            category_scores[name] * weight
            for name, weight in {
                "project_information": 0.25,
                "pricing": 0.15,
                "units": 0.15,
                "amenities": 0.15,
                "architecture": 0.10,
                "marketing": 0.20,
            }.items()
        )

        missing_fields = [name for name, score in field_scores.items() if score == 0]
        warnings = self._warnings(marketing_score, duplicate_amenities, empty_amenities, units)
        warnings.append("Project type, status, and marketing themes cannot be evaluated because they are not represented by the current ProjectKnowledge schema.")
        strengths = self._strengths(category_scores)
        recommendations = self._recommendations(category_scores, missing_fields)
        completed_fields = sum(score == 1.0 for score in field_scores.values())
        return KnowledgeEvaluation(
            evaluator_version=EVALUATOR_VERSION,
            project=str(project.get("name") or project_name),
            json_validity={"valid": True, "score": 10, "error": ""},
            category_scores=category_scores,
            overall_score=round(overall_score, 1),
            completeness_percentage=round(completed_fields / len(field_scores) * 100, 1),
            completed_fields=completed_fields,
            total_fields=len(field_scores),
            missing_fields=missing_fields,
            warnings=warnings,
            strengths=strengths,
            recommendations=recommendations,
        )

    def save_report(self, evaluation: KnowledgeEvaluation, knowledge_path: Path) -> Path:
        """Write ``<project>-evaluation.json`` to the required reports directory."""
        reports_directory = KNOWLEDGE_OUTPUT_DIRECTORY.parent / "reports"
        reports_directory.mkdir(parents=True, exist_ok=True)
        destination = reports_directory / f"{knowledge_path.stem}-evaluation.json"
        destination.write_text(json.dumps(evaluation.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return destination

    def format_report(self, evaluation: KnowledgeEvaluation) -> str:
        """Return a readable terminal summary of an evaluation."""
        lines = [
            "Knowledge Evaluation Report",
            evaluation.evaluator_version,
            f"Project: {evaluation.project}",
            f"JSON Validity: {evaluation.json_validity['score']}/10",
            f"Overall Score: {evaluation.overall_score}/100",
            f"Completeness: {evaluation.completeness_percentage}% ({evaluation.completed_fields}/{evaluation.total_fields} fields)",
            f"Source Utilization: {evaluation.source_utilization_score}%",
            f"Source-Conditioned Project Completeness: {evaluation.project_completeness_score}%",
            "Category Scores:",
        ]
        lines.extend(
            f"- {name.replace('_', ' ').title()}: {score}/100"
            for name, score in evaluation.category_scores.items()
        )
        for label, values in (
            ("Missing Fields", evaluation.missing_fields),
            ("Warnings", evaluation.warnings),
            ("Strengths", evaluation.strengths),
            ("Recommendations", evaluation.recommendations),
        ):
            lines.append(f"{label}: " + (", ".join(values) if values else "None"))
        return "\n".join(lines)

    @staticmethod
    def _invalid_json_report(project: str, error: str) -> KnowledgeEvaluation:
        return KnowledgeEvaluation(
            evaluator_version=EVALUATOR_VERSION,
            project=project,
            json_validity={"valid": False, "score": 0, "error": error},
            category_scores={name: 0.0 for name in ("project_information", "pricing", "units", "amenities", "architecture", "marketing")},
            overall_score=0.0,
            completeness_percentage=0.0,
            completed_fields=0,
            total_fields=0,
            missing_fields=[],
            warnings=["Knowledge JSON is invalid and could not be evaluated."],
            strengths=[],
            recommendations=["Fix JSON validity before evaluating extraction quality."],
        )

    @staticmethod
    def _warnings(marketing_score: float, duplicates: list[str], empty_amenities: list[Any], units: list[dict[str, Any]]) -> list[str]:
        warnings: list[str] = []
        if marketing_score < 50:
            warnings.append("Marketing section is mostly empty.")
        if duplicates:
            warnings.append("Duplicate amenities: " + ", ".join(duplicates))
        if empty_amenities:
            warnings.append("Amenities contain empty values.")
        if not units:
            warnings.append("No units were extracted.")
        return warnings

    @staticmethod
    def _strengths(scores: dict[str, float]) -> list[str]:
        labels = {
            "project_information": "Project information extracted well.",
            "pricing": "Pricing extracted well.",
            "units": "Unit information extracted well.",
            "amenities": "Amenities extracted well.",
            "architecture": "Architecture extracted well.",
            "marketing": "Marketing information extracted well.",
        }
        return [labels[name] for name, score in scores.items() if score >= 80]

    @staticmethod
    def _recommendations(scores: dict[str, float], missing_fields: list[str]) -> list[str]:
        recommendations: list[str] = []
        labels = {
            "project_information": "Improve extraction of project information.",
            "pricing": "Improve extraction of pricing information.",
            "units": "Improve extraction of unit details.",
            "amenities": "Improve extraction of amenities.",
            "architecture": "Improve extraction of architectural details.",
            "marketing": "Improve marketing reasoning from catalogue evidence.",
        }
        recommendations.extend(labels[name] for name, score in scores.items() if score < 80)
        recommendations.append("Add project type, status, and marketing themes to the knowledge schema before measuring their extraction quality.")
        return recommendations


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


PLACEHOLDER_VALUES = frozenset({"", "-", "--", "n/a", "na", "none", "null", "unknown", "unspecified", "not available", "not provided", "tbd"})


def _meaningful_text(value: Any) -> bool:
    """Return whether a text value contains information rather than a placeholder."""
    return isinstance(value, str) and " ".join(value.split()).casefold() not in PLACEHOLDER_VALUES


def _meaningful_score(value: Any) -> float:
    """Score scalars only when they are non-placeholder, non-empty values."""
    if _meaningful_text(value):
        return 1.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 1.0 if math.isfinite(value) and value > 0 else 0.0
    return 0.0


def _list_score(value: Any, target_count: int) -> float:
    """Score a list by the number of distinct, meaningful text entries it contains."""
    if not isinstance(value, list):
        return 0.0
    meaningful_entries = {" ".join(item.split()).casefold() for item in value if _meaningful_text(item)}
    return min(len(meaningful_entries) / target_count, 1.0)


def _coverage(items: list[dict[str, Any]], field: str) -> float:
    if not items:
        return 0.0
    return sum(_meaningful_score(item.get(field)) for item in items) / len(items)


def _average(scores: dict[str, float], fields: list[str]) -> float:
    return sum(scores[field] for field in fields) / len(fields)
