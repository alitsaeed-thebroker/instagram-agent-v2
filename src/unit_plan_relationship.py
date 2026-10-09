"""Deterministic, source-backed unit/plan relationships.

Supports explicit labelled complete PDF pages and structural catalogue
adapters that recompute every floor join from source bytes. OCR, vision
transcriptions, arbitrary cross-page joins, and caller-supplied VERIFIED flags
are never proof. Unsupported brochures go to review; extend the parser with
source fixtures, not confidence thresholds.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import fitz

VERSION = "1.0.0"
UNIT_TYPES = frozenset({"unit_layout", "apartment_layout", "office_layout", "villa_layout", "commercial_unit_layout"})
LABELS = {
    "project_id": "Project", "unit_type": "Unit Type", "bedrooms": "Bedrooms",
    "area_sqm": "Area sqm", "floor": "Floor", "tower": "Tower",
    "building": "Building", "context": "Context", "bathrooms": "Bathrooms",
    "unit_number": "Unit Number", "orientation": "Orientation", "balcony": "Balcony",
    "terrace": "Terrace", "dimensions": "Dimensions",
    "commercial_residential_classification": "Classification",
}


def _normalized(value):
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def verify_unit_plan_relationship(asset: dict) -> dict:
    """Recompute proof from source bytes, never trust a serialized proof object."""
    reasons = []
    identity = {}
    evidence = {}
    provenance = {key: asset.get(key) for key in (
        "project_id", "source_document", "source_document_path", "source_page",
        "source_document_hash", "asset_id", "source_path", "source_hash", "asset_type",
    )}
    if asset.get("source_kind") == "pdf_villa_plan_leaf":
        from src.unit_plan_catalogue import verify_catalogue_leaf
        identity, evidence, metadata, reasons = verify_catalogue_leaf(asset)
        provenance["source_region"] = asset.get("source_region")
        payload = {"schema_version": VERSION, "authority": "deterministic_catalogue_villa_relationship",
                   "provenance": provenance, "unit_identity": identity, "evidence": evidence,
                   "catalogue_relationship": metadata,
                   "status": "REVIEW_REQUIRED" if reasons else "VERIFIED", "reasons": reasons}
        payload["relationship_id"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return payload
    if asset.get("asset_type") not in UNIT_TYPES:
        reasons.append("floor/site/master/technical plan is not an individual unit plan")
    if str(asset.get("relationship_status") or "").upper() in {"AMBIGUOUS", "CONFLICTED", "PROBABLE"}:
        reasons.append("existing relationship ambiguity or conflict requires review")
    if not all(provenance.values()):
        reasons.append("missing exact project/document/page/hash/asset provenance")
    if type(asset.get("source_page")) is not int or asset["source_page"] < 1:
        reasons.append("source page must be a positive one-based integer")
    if asset.get("source_kind") != "pdf_page_render" or asset.get("contains_entire_page") is not True:
        reasons.append("only an exact complete PDF page render is supported")
    if asset.get("render_dpi") != 300:
        reasons.append("complete plan must use the canonical 300 dpi render")
    if not reasons:
        try:
            document_path = Path(asset["source_document_path"])
            if document_path.name != asset["source_document"]:
                reasons.append("source document filename mismatch")
            pdf_bytes = document_path.read_bytes()
            image_bytes = Path(asset["source_path"]).read_bytes()
            if hashlib.sha256(pdf_bytes).hexdigest() != asset["source_document_hash"]:
                reasons.append("source document hash mismatch")
            if hashlib.sha256(image_bytes).hexdigest() != asset["source_hash"]:
                reasons.append("exact plan asset hash mismatch")
            if not reasons:
                with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
                    page = document[asset["source_page"] - 1]
                    render = page.get_pixmap(dpi=300, alpha=True).tobytes("png")
                    if render != image_bytes:
                        reasons.append("plan asset is not the exact source page render")
                    text = page.get_text("text")
                if len(re.findall(r"^\s*UNIT PLAN\s*$", text, re.I | re.M)) != 1:
                    reasons.append("missing or ambiguous individual UNIT PLAN scope")
                if re.search(r"\b(?:floor\s+plan|site\s+plan|master\s*plan|typical\s+floor)\b", text, re.I):
                    reasons.append("non-unit plan scope in source page")
                for field, label in LABELS.items():
                    matches = re.findall(r"^[ \t]*" + re.escape(label) + r"[ \t]*:[ \t]*([^\r\n]+)", text, re.I | re.M)
                    if len(matches) > 1:
                        reasons.append(f"ambiguous or conflicting source labels: {field}")
                    elif matches:
                        value = matches[0].strip()
                        if field in {"bedrooms", "bathrooms"}:
                            if not re.fullmatch(r"\d+", value):
                                reasons.append(f"invalid source number: {field}"); continue
                            value = int(value)
                        elif field == "area_sqm":
                            if not re.fullmatch(r"\d+(?:\.\d+)?", value) or float(value) <= 0:
                                reasons.append("invalid source area"); continue
                            value = float(value)
                        elif field == "dimensions":
                            value = [part.strip() for part in value.split(";")]
                        elif _normalized(value) in {"unknown", "n/a", "none", "unverified", "?"}:
                            continue
                        identity[field] = value
                        evidence[field] = [{
                            "source_project": asset["project_id"], "source_document": asset["source_document"],
                            "source_document_hash": asset["source_document_hash"], "source_page": asset["source_page"],
                            "source_hash": asset["source_hash"], "asset_id": asset["asset_id"],
                            "value": value, "evidence_text": f"{label}: {matches[0]}",
                            "extraction_method": "deterministic_pdf_label",
                        }]
                for field in ("project_id", "unit_type", "bedrooms", "area_sqm"):
                    if field not in identity:
                        reasons.append(f"missing source-visible required field: {field}")
                if not any(field in identity for field in ("floor", "tower", "building", "context")):
                    reasons.append("missing floor/tower/building/context relationship")
                if identity.get("project_id") != asset["project_id"]:
                    reasons.append("source project mismatch")
                for field, value in (asset.get("unit_identity") or {}).items():
                    if value is not None and value != "" and _normalized(value) != _normalized(identity.get(field)):
                        # Numeric equality must not be lost to 142 versus 142.0.
                        if type(value) in (int, float) and value == identity.get(field):
                            continue
                        reasons.append(f"metadata conflicts with deterministic source: {field}")
        except (OSError, ValueError, TypeError, IndexError, RuntimeError) as error:
            reasons.append(f"source proof unavailable: {type(error).__name__}")
    identity.pop("project_id", None)
    payload = {"schema_version": VERSION, "authority": "deterministic_pdf_labels_and_exact_render",
               "provenance": provenance, "unit_identity": identity, "evidence": evidence,
               "status": "REVIEW_REQUIRED" if reasons else "VERIFIED", "reasons": reasons}
    payload["relationship_id"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def relationship_errors(record: dict, *, expected_project=None, asset_id=None, source_path=None) -> list[str]:
    """Validate persisted canonical proof and bind it to the actual consumer asset."""
    proof = verify_unit_plan_relationship(record)
    errors = list(proof["reasons"])
    if record.get("unit_plan_relationship") != proof:
        errors.append("canonical unit-plan relationship is missing, stale, or altered")
    if record.get("evidence") != proof["evidence"]:
        errors.append("canonical field evidence is missing or altered")
    if expected_project is not None and record.get("project_id") != expected_project:
        errors.append("plan project mismatch")
    if asset_id is not None and record.get("asset_id") != asset_id:
        errors.append("wrong plan asset substitution")
    if source_path is not None:
        try:
            if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() != record.get("source_hash"):
                errors.append("wrong plan image substitution")
        except (OSError, TypeError):
            errors.append("actual production plan image is unavailable")
    return list(dict.fromkeys(errors))
