"""Beverly Hills catalogue adapter: explicit villa sections and numbered legends.

PDF spreads contain two printed pages. Only entire printed leaves are extracted;
the plan, legend, area table, and all printed labels remain together.
Cross-page membership requires contiguous floors and identical explicit area
tables within one unique villa type section in the same source document.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
from pathlib import Path
import re

import fitz

ADAPTER = "beverly_hills_villa_catalogue_v1"
FLOORS = ("Ground Floor", "First Floor", "Second Floor")
AREA_LABELS = {
    "ground": "Ground F. Area", "first": "First F. Area",
    "penthouse": "Penthouse F. Area", "built_up": "Buildup Area",
}


def _leaf_rect(page, side):
    middle = (page.rect.x0 + page.rect.x1) / 2
    return fitz.Rect(page.rect.x0 if side == "left" else middle, page.rect.y0,
                     middle if side == "left" else page.rect.x1, page.rect.y1)


def _text_rows(page, rect):
    result = []
    data = page.get_text("dict", clip=rect, flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
    for block in data["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            result.append({"text": "".join(span["text"] for span in spans).strip(),
                           "bbox": list(line["bbox"]),
                           "font_sizes": [round(span["size"], 4) for span in spans],
                           "visible": all(span.get("alpha", 255) > 0 for span in spans)})
    return result


def _table(text):
    values = {}
    errors = []
    for key, label in AREA_LABELS.items():
        hits = re.findall(re.escape(label) + r":\s*(\d+(?:\.\d+)?)\s*m\s*[2²]", text, re.I)
        if len(hits) > 1:
            errors.append(f"ambiguous area table: {label}")
        elif hits:
            values[key] = Decimal(hits[0])
    for key in ("ground", "first", "built_up"):
        if key not in values:
            errors.append(f"missing area table field: {key}")
    if any(value <= 0 for value in values.values()):
        errors.append("non-positive source area")
    if not errors and sum(value for key, value in values.items() if key != "built_up") != values["built_up"]:
        errors.append("source floor areas conflict with stated built-up total")
    return values, errors


def _rooms(rows):
    # Join wrapped M.BED / ROOM text before parsing. Numbered legends, not
    # inferred room geometry, prove the count; MAID ROOM is never a bedroom.
    text = "\n".join(row["text"] for row in rows)
    matches = re.findall(r"(?m)^(\d{2})\s*\|\s*([^\n]+(?:\nROOM\b)?)", text)
    rooms = [{"number": number, "label": re.sub(r"\s+", " ", label).strip(),
              "bedroom": bool(re.fullmatch(r"(?:M\.?\s*)?BED\s*ROOM", label.replace("\n", " ").strip(), re.I))}
             for number, label in matches]
    numbers = [int(room["number"]) for room in rooms]
    errors = []
    if not numbers or len(set(numbers)) != len(numbers) or set(numbers) != set(range(1, max(numbers) + 1)):
        errors.append("room legend numbers are missing, duplicated, or non-contiguous")
    return rooms, errors


def inspect_catalogue(document, project):
    """Return source candidates with evidence and explicit failure reasons."""
    if project != "Beverly Hills":
        return []
    texts = [page.get_text() for page in document]
    anchors = [n + 1 for n, text in enumerate(texts)
               if re.search(r"Beverly Hills features only standalone villas", text)]
    sections = [n + 1 for n, text in enumerate(texts) if re.search(r"(?m)^Plans & Layouts$", text)]
    if len(anchors) != 1 or len(sections) != 1:
        return []
    starts = []
    for index, text in enumerate(texts):
        if index + 1 <= sections[0]:
            continue
        types = re.findall(r"(?m)^Type ([A-Z])$", text)
        if types:
            starts.append((index, types))
    candidates = []
    for index, types in starts:
        errors = []
        unit_type = "Type " + types[0]
        if len(types) != 1 or sum(unit_type in ["Type " + t for t in ts] for _, ts in starts) != 1:
            errors.append("ambiguous or duplicated villa type section")
        members = []
        for page_index in (index, index + 1):
            if page_index >= len(document):
                continue
            page = document[page_index]
            if abs(page.rect.width / page.rect.height - 2) > .01 or page.rotation:
                errors.append("unsupported or rotated catalogue spread")
                continue
            for side in ("left", "right"):
                rect = _leaf_rect(page, side)
                rows = _text_rows(page, rect)
                text = "\n".join(row["text"] for row in rows)
                headings = [row["text"] for row in rows if row["text"] in FLOORS]
                if not headings:
                    continue
                if len(headings) != 1:
                    errors.append("multiple floor plans in one printed leaf")
                    continue
                table, table_errors = _table(text)
                rooms, room_errors = _rooms(rows)
                errors.extend(table_errors + room_errors)
                if any(not row["visible"] for row in rows):
                    errors.append("invisible source labels cannot prove a relationship")
                # Source room identifiers must actually appear within the drawing.
                diagram = fitz.Rect(rect.x0 + rect.width * .20, rect.y0 + rect.height * .18,
                                    rect.x0 + rect.width * .78, rect.y0 + rect.height * .88)
                markers = [row["text"] for row in rows if re.fullmatch(r"\d{2}", row["text"])
                           and diagram.contains(fitz.Rect(row["bbox"]))]
                if sorted(markers) != sorted(room["number"] for room in rooms):
                    errors.append("numbered room legend does not match exact plan markers")
                members.append({"source_page": page_index + 1, "side": side, "source_region": list(rect),
                                "floor": headings[0], "areas": {k: float(v) for k, v in table.items()},
                                "rooms": rooms, "source_rows": rows})
        expected = ["Ground Floor", "First Floor"]
        if [member["floor"] for member in members] != expected:
            errors.append("complete unambiguous two-floor villa plan set is unavailable")
        if any("penthouse" in member["areas"] for member in members):
            errors.append("penthouse area versus Second Floor heading needs source clarification")
        if members and any(member["areas"] != members[0]["areas"] for member in members[1:]):
            errors.append("floor pages carry conflicting area tables")
        if not members or members[0]["source_page"] != index + 1 or members[0]["side"] != "right":
            errors.append("type caption is not paired with the ground floor printed leaf")
        title_rows = _text_rows(document[index], _leaf_rect(document[index], "left"))
        title_text = "\n".join(row["text"] for row in title_rows)
        advertised = re.findall(r"(?m)^(\d+(?:\.\d+)?)\s*M\s*[2²]$", title_text)
        candidates.append({"unit_type": unit_type, "type_page": index + 1,
                           "project_anchor_page": anchors[0], "section_anchor_page": sections[0],
                           "advertised_area_sqm": float(advertised[0]) if len(advertised) == 1 else None,
                           "advertised_area_meaning": "UNSPECIFIED_IN_SOURCE",
                           "members": members, "bedrooms": sum(room["bedroom"] for member in members for room in member["rooms"]),
                           "area_sqm": members[0]["areas"].get("built_up") if members else None,
                           "area_basis": "built_up", "reasons": list(dict.fromkeys(errors))})
    return candidates


def leaf_asset_id(document_hash, page, region):
    token = f"{ADAPTER}|{document_hash}|{page}|{region}"
    return "villa_leaf_" + hashlib.sha256(token.encode()).hexdigest()[:20]


def verify_catalogue_leaf(asset):
    """Validate exact leaf bytes and recompute all cross-page joins from PDF."""
    reasons = []
    identity = {}
    evidence = {}
    metadata = {}
    try:
        if asset.get("project_id") != "Beverly Hills" or asset.get("asset_type") != "villa_layout":
            reasons.append("catalogue adapter cannot substitute project or non-villa plan type")
        if str(asset.get("relationship_status") or "").upper() in {"AMBIGUOUS", "CONFLICTED", "PROBABLE"}:
            reasons.append("existing relationship ambiguity or conflict requires review")
        path = Path(asset["source_document_path"])
        pdf_bytes = path.read_bytes()
        document_hash = hashlib.sha256(pdf_bytes).hexdigest()
        if path.name != asset.get("source_document") or document_hash != asset.get("source_document_hash"):
            reasons.append("source document identity/hash mismatch")
        if asset.get("render_dpi") != 300 or asset.get("contains_complete_plan_leaf") is not True:
            reasons.append("exact complete printed plan leaf at 300 dpi is required")
        image_bytes = Path(asset["source_path"]).read_bytes()
        if hashlib.sha256(image_bytes).hexdigest() != asset.get("source_hash"):
            reasons.append("exact plan asset hash mismatch")
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            candidates = inspect_catalogue(document, asset.get("project_id"))
            matches = [(candidate, member) for candidate in candidates for member in candidate["members"]
                       if member["source_page"] == asset.get("source_page")
                       and member["source_region"] == asset.get("source_region")]
            if len(matches) != 1:
                reasons.append("plan leaf does not have one exact catalogue relationship")
            else:
                candidate, member = matches[0]
                reasons.extend(candidate["reasons"])
                expected_id = leaf_asset_id(document_hash, member["source_page"], member["source_region"])
                if asset.get("asset_id") != expected_id:
                    reasons.append("exact plan asset identity mismatch")
                render = document[member["source_page"] - 1].get_pixmap(
                    dpi=300, alpha=True, clip=fitz.Rect(member["source_region"])).tobytes("png")
                if render != image_bytes:
                    reasons.append("asset is not the exact complete printed plan leaf")
                identity = {"unit_type": candidate["unit_type"], "area_sqm": candidate["area_sqm"],
                            "bedrooms": candidate["bedrooms"], "floor": member["floor"],
                            "context": "standalone villa; complete linked floor set"}
                unit_scope_id = hashlib.sha256(f"{document_hash}|{asset['project_id']}|{candidate['unit_type']}".encode()).hexdigest()
                metadata = {"adapter": ADAPTER, "unit_scope_id": unit_scope_id, "area_basis": "built_up",
                            "advertised_area_sqm": candidate["advertised_area_sqm"],
                            "advertised_area_meaning": candidate["advertised_area_meaning"],
                            "required_plan_asset_ids": [leaf_asset_id(document_hash, m["source_page"], m["source_region"])
                                                        for m in candidate["members"]],
                            "member_pages": [m["source_page"] for m in candidate["members"]],
                            "source_region": member["source_region"], "protected_source_rows": member["source_rows"]}
                for field, value in identity.items():
                    evidence[field] = [{"source_project": asset["project_id"],
                        "source_document": asset["source_document"], "source_document_hash": document_hash,
                        "source_page": asset["source_page"], "source_hash": asset["source_hash"], "asset_id": asset["asset_id"],
                        "value": value, "extraction_method": ADAPTER,
                        "supporting_source": {"type_page": candidate["type_page"],
                            "project_anchor_page": candidate["project_anchor_page"],
                            "members": [{"page": m["source_page"], "region": m["source_region"],
                                         "floor": m["floor"], "area_table": m["areas"], "room_legend": m["rooms"]}
                                        for m in candidate["members"]]}}]
        supplied = asset.get("unit_identity") or {}
        for field, value in supplied.items():
            if value not in (None, "") and value != identity.get(field):
                reasons.append(f"metadata conflicts with deterministic source: {field}")
    except (KeyError, OSError, ValueError, TypeError, IndexError, RuntimeError) as error:
        reasons.append(f"catalogue source proof unavailable: {type(error).__name__}")
    return identity, evidence, metadata, list(dict.fromkeys(reasons))


def extract_catalogue_leaves(project, pdf_path, destination):
    """Recover complete printed pages, without cropping any technical drawing."""
    pdf_path = Path(pdf_path).resolve()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    document_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assets = []
    with fitz.open(pdf_path) as document:
        candidates = inspect_catalogue(document, project)
        for candidate in candidates:
            for member in candidate["members"]:
                page = document[member["source_page"] - 1]
                pixmap = page.get_pixmap(dpi=300, alpha=True, clip=fitz.Rect(member["source_region"]))
                data = pixmap.tobytes("png")
                asset_id = leaf_asset_id(document_hash, member["source_page"], member["source_region"])
                image_path = destination / f"{asset_id}.png"
                image_path.write_bytes(data)
                assets.append({"asset_id": asset_id, "asset_type": "villa_layout", "project_id": project,
                    "source_document": pdf_path.name, "source_document_path": str(pdf_path),
                    "source_document_hash": document_hash, "source_page": member["source_page"],
                    "source_region": member["source_region"], "source_kind": "pdf_villa_plan_leaf",
                    "contains_complete_plan_leaf": True, "render_dpi": 300,
                    "source_path": str(image_path), "source_hash": hashlib.sha256(data).hexdigest(),
                    "sha256": hashlib.sha256(data).hexdigest(), "source_document_sha256": document_hash,
                    "width": pixmap.width, "height": pixmap.height,
                    "filename": image_path.name, "orientation": "square", "image_index": 0,
                    "extraction_method": ADAPTER, "extraction_fidelity": "complete_printed_plan_leaf",
                    "byte_preserving": False, "contains_entire_page": False, "status": "success",
                    "plan_completeness_status": "COMPLETE", "plan_legibility_status": "READABLE",
                    "relationship_status": "UNVERIFIED", "unit_identity": {}})
    return assets, candidates
