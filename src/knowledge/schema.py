"""Dataclasses that define the structured project knowledge artifact.

The classes in this module intentionally contain no extraction or AI logic.  They
are a stable, JSON-friendly contract for knowledge produced by a later stage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


IDENTITY_FIELDS = ("project_name", "developer_name", "project_type", "location")


@dataclass
class ProjectIdentity:
    """The four canonical identity facts; no marketing brand is stored here."""

    project_name: str = ""
    developer_name: str = ""
    project_type: str = ""
    location: str = ""


@dataclass
class ProjectDetails:
    """The identifying information for a real-estate project."""

    name: str = ""
    developer: str = ""
    location: str = ""
    description: str = ""


@dataclass
class Branding:
    name: str = ""
    tagline: str = ""
    tone_of_voice: str = ""
    key_messages: list[str] = field(default_factory=list)


@dataclass
class Pricing:
    currency: str = ""
    starting_price: float | None = None
    payment_plan: str = ""
    notes: str = ""


@dataclass
class Unit:
    """A type of unit offered by the project."""

    name: str = ""
    bedrooms: int | None = None
    bathrooms: int | None = None
    area_sqm: float | None = None
    starting_price: float | None = None
    features: list[str] = field(default_factory=list)


@dataclass
class Architecture:
    style: str = ""
    architect: str = ""
    materials: list[str] = field(default_factory=list)
    design_features: list[str] = field(default_factory=list)


@dataclass
class Investment:
    highlights: list[str] = field(default_factory=list)
    expected_return: str = ""
    rental_potential: str = ""
    completion_date: str = ""


@dataclass
class Marketing:
    target_audience: list[str] = field(default_factory=list)
    selling_points: list[str] = field(default_factory=list)
    calls_to_action: list[str] = field(default_factory=list)


@dataclass
class ProjectKnowledge:
    """Complete, serializable knowledge captured for one real-estate project."""

    project: ProjectDetails = field(default_factory=ProjectDetails)
    branding: Branding = field(default_factory=Branding)
    pricing: Pricing = field(default_factory=Pricing)
    units: list[Unit] = field(default_factory=list)
    amenities: list[str] = field(default_factory=list)
    architecture: Architecture = field(default_factory=Architecture)
    investment: Investment = field(default_factory=Investment)
    marketing: Marketing = field(default_factory=Marketing)
    project_identity: ProjectIdentity = field(default_factory=ProjectIdentity)
    fact_provenance: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    commercial_intelligence: dict[str, Any] = field(default_factory=dict)
    canonical_intelligence: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return human-readable errors for required knowledge fields."""
        errors: list[str] = []
        # Missing identity is controlled downstream rather than invented.  Legacy
        # project fields remain accepted while artifacts migrate to v2.
        canonical = self.canonical_intelligence
        # A validated intake namespace identifies ownership, not a public fact.
        # Keep conflicting display names unavailable instead of inventing one.
        has_namespace = isinstance(canonical, dict) and bool(str(canonical.get("project_namespace") or "").strip())
        if not (self.project_identity.project_name or self.project.name).strip() and not has_namespace:
            errors.extend(("project.name is required", "project_identity.project_name is unavailable"))
        # Sparse projects are valid Department 2 inputs. Missing location is
        # represented as unknown downstream rather than fabricated or rejected.
        if canonical:
            try:
                from src.knowledge.relational import CanonicalIntelligence
                CanonicalIntelligence.from_dict(canonical)
            except ValueError as exc:
                errors.append(str(exc))
        return errors

    def is_valid(self) -> bool:
        """Return whether all required fields are present."""
        return not self.validate()

    def to_dict(self) -> dict[str, Any]:
        """Convert this object to JSON-compatible primitive values."""
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize this object as JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectKnowledge":
        """Build a knowledge object from a JSON-compatible mapping."""
        if not isinstance(data, dict):
            raise ValueError("Knowledge data must be a JSON object")

        def object_value(key: str) -> dict[str, Any]:
            value = data.get(key, {})
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            return value

        def list_value(key: str) -> list[Any]:
            value = data.get(key, [])
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list")
            return value

        units = list_value("units")
        if not all(isinstance(unit, dict) for unit in units):
            raise ValueError("units must contain JSON objects")

        identity_data = data.get("project_identity")
        if identity_data is None:
            project = object_value("project")
            identity_data = {
                "project_name": project.get("name", ""),
                "developer_name": project.get("developer", ""),
                "project_type": "",
                "location": project.get("location", ""),
            }
        if not isinstance(identity_data, dict) or set(identity_data) - set(IDENTITY_FIELDS):
            raise ValueError("project_identity must contain only the four canonical identity fields")
        identity_data = {name: str(identity_data.get(name) or "") for name in IDENTITY_FIELDS}
        provenance = data.get("fact_provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("fact_provenance must be an object")
        commercial = data.get("commercial_intelligence", {})
        if not isinstance(commercial, dict):
            raise ValueError("commercial_intelligence must be an object")
        canonical = data.get("canonical_intelligence", {})
        if not isinstance(canonical, dict):
            raise ValueError("canonical_intelligence must be an object")
        return cls(
            project=ProjectDetails(**object_value("project")),
            branding=Branding(**object_value("branding")),
            pricing=Pricing(**object_value("pricing")),
            units=[Unit(**unit) for unit in units],
            amenities=list_value("amenities"),
            architecture=Architecture(**object_value("architecture")),
            investment=Investment(**object_value("investment")),
            marketing=Marketing(**object_value("marketing")),
            project_identity=ProjectIdentity(**identity_data),
            fact_provenance=provenance,
            commercial_intelligence=commercial,
            canonical_intelligence=canonical,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ProjectKnowledge":
        """Deserialize a project knowledge JSON document."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Knowledge JSON is invalid") from error
        return cls.from_dict(data)


def serialize_project_knowledge(knowledge: ProjectKnowledge) -> str:
    """Serialize a ``ProjectKnowledge`` artifact to JSON."""
    return knowledge.to_json()


def deserialize_project_knowledge(payload: str) -> ProjectKnowledge:
    """Deserialize a ``ProjectKnowledge`` artifact from JSON."""
    return ProjectKnowledge.from_json(payload)
