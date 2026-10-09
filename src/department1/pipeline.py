\
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


DEPARTMENT1_CONTRACT_VERSION = "d1.real-estate-intelligence.v1.1"
SUPPORTED_TEXT = {".txt", ".md"}
SUPPORTED_DOCX = {".docx"}
SUPPORTED_PDF = {".pdf"}
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_EXTENSIONS = SUPPORTED_TEXT | SUPPORTED_DOCX | SUPPORTED_PDF | SUPPORTED_IMAGES

GLOBAL_EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "output", "cache",
    "brand", "brands", "assets", "logos",
    "publishing", "visual-review", "campaigns", "creative-direction", "editorial-copy",
}


class Department1Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Department1Config:
    model: str = os.getenv("D1_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"
    allow_external_ai: bool = (
        os.getenv("D1_ALLOW_EXTERNAL_AI", "true").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    max_text_chars_per_call: int = int(os.getenv("D1_MAX_TEXT_CHARS", "80000"))
    temperature: float = 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "-", value.strip(), flags=re.UNICODE).strip("-._")
    return cleaned or "project"


def project_storage_key(project: str) -> str:
    """Stable namespace key that cannot merge punctuation-distinct folders."""
    return _slug(project) + "--" + hashlib.sha256(project.strip().encode("utf-8")).hexdigest()[:16]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as tmp:
        tmp.write(raw)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _require_package(name: str, install_hint: str) -> None:
    raise Department1Error(
        f"Required package '{name}' is not installed. Install with: {install_hint}"
    )


class Department1Pipeline:
    """
    Canonical Department 1 cognition:
        INPUT -> READ -> UNDERSTAND -> ANALYZE -> CLASSIFY -> EXTRACT -> D2

    Project isolation, provenance, authenticity, validation and fail-closed
    behavior are controls across all stages, not substitute stages.
    """

    def __init__(
        self,
        project_root: str | Path,
        project_name: str | None = None,
        *,
        output_root: str | Path = "output/department1",
        config: Department1Config | None = None,
        client: Any | None = None,
        source_paths: Iterable[str | Path] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        if not self.project_root.exists() or not self.project_root.is_dir():
            raise Department1Error(f"Project input directory not found: {self.project_root}")

        self.project_name = (project_name or self.project_root.name).strip()
        if not self.project_name:
            raise Department1Error("Project name cannot be empty.")

        self.project_slug = project_storage_key(self.project_name)
        self.output_dir = Path(output_root).resolve() / self.project_slug
        self.config = config or Department1Config()
        self.client = client
        self.source_paths = tuple(Path(p).resolve() for p in source_paths) if source_paths is not None else None
        if self.source_paths is not None:
            for source in self.source_paths:
                if not source.is_file():
                    raise Department1Error(f"Project source file not found: {source}")
                try:
                    source.relative_to(self.project_root)
                except ValueError as exc:
                    raise Department1Error(
                        f"Project source escapes project root: {source}"
                    ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        input_manifest = self.input_stage()
        read_package = self.read_stage(input_manifest)
        understanding = self.understand_stage(read_package)
        analysis = self.analyze_stage(read_package, understanding)
        classification = self.classify_stage(read_package, understanding, analysis)
        extracted = self.extract_stage(
            read_package, understanding, analysis, classification
        )
        handoff = self.build_department2_handoff(
            input_manifest,
            read_package,
            understanding,
            analysis,
            classification,
            extracted,
        )
        self.validate_handoff(handoff)

        _atomic_json(self.output_dir / "department2-handoff.json", handoff)
        _atomic_json(
            self.output_dir / "run-summary.json",
            {
                "contract_version": DEPARTMENT1_CONTRACT_VERSION,
                "project": self.project_name,
                "project_slug": self.project_slug,
                "completed_at": _utc_now(),
                "status": "PASS",
                "pipeline": [
                    "INPUT",
                    "READ",
                    "UNDERSTAND",
                    "ANALYZE",
                    "CLASSIFY",
                    "EXTRACT",
                    "DEPARTMENT_2_HANDOFF",
                ],
                "handoff_path": str(self.output_dir / "department2-handoff.json"),
            },
        )
        return handoff

    # ------------------------------------------------------------------
    # 1. INPUT
    # ------------------------------------------------------------------

    def input_stage(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []

        candidates = (
            sorted(self.source_paths)
            if self.source_paths is not None
            else sorted(self.project_root.rglob("*"))
        )
        for path in candidates:
            if not path.is_file():
                continue
            try:
                path.resolve().relative_to(self.project_root)
            except ValueError as exc:
                raise Department1Error("Project source resolves outside project root.") from exc
            rel = path.relative_to(self.project_root)
            if any(part.lower() in GLOBAL_EXCLUDED_DIRS for part in rel.parts[:-1]):
                continue
            ext = path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            files.append(
                {
                    "source_id": self._source_id(rel.as_posix(), _sha256_file(path)),
                    "project": self.project_name,
                    "relative_path": rel.as_posix(),
                    "absolute_path": str(path),
                    "extension": ext,
                    "mime_type": mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                    "sha256": _sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )

        if not files:
            raise Department1Error(
                f"No supported project source files found under {self.project_root}"
            )

        manifest = {
            "stage": "INPUT",
            "contract_version": DEPARTMENT1_CONTRACT_VERSION,
            "project": self.project_name,
            "project_root": str(self.project_root),
            "created_at": _utc_now(),
            "files": files,
        }
        _atomic_json(self.output_dir / "01-input.json", manifest)
        return manifest

    # ------------------------------------------------------------------
    # 2. READ
    # ------------------------------------------------------------------

    def read_stage(self, input_manifest: dict[str, Any]) -> dict[str, Any]:
        sources: list[dict[str, Any]] = []

        for item in input_manifest["files"]:
            path = Path(item["absolute_path"])
            ext = path.suffix.lower()

            if ext in SUPPORTED_TEXT:
                source = self._read_text(item, path)
            elif ext in SUPPORTED_DOCX:
                source = self._read_docx(item, path)
            elif ext in SUPPORTED_PDF:
                source = self._read_pdf(item, path)
            elif ext in SUPPORTED_IMAGES:
                source = self._read_image(item, path)
            else:  # protected by input_stage
                continue

            self._assert_project(source)
            sources.append(source)

        package = {
            "stage": "READ",
            "contract_version": DEPARTMENT1_CONTRACT_VERSION,
            "project": self.project_name,
            "created_at": _utc_now(),
            "sources": sources,
            "controls": {
                "project_isolation": True,
                "provenance_required": True,
                "original_file_hash_preserved": True,
                "authentic_source_assets_only": True,
            },
        }
        _atomic_json(self.output_dir / "02-read.json", package)
        return package

    def _read_text(self, item: dict[str, Any], path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        blocks = []
        for idx, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                blocks.append(
                    {
                        "text": line,
                        "provenance": self._prov(
                            item, locator={"type": "line", "start": idx, "end": idx}
                        ),
                    }
                )
        return self._source_record(item, "text", blocks=blocks, assets=[])

    def _read_docx(self, item: dict[str, Any], path: Path) -> dict[str, Any]:
        try:
            from docx import Document
        except ImportError:  # pragma: no cover
            _require_package("python-docx", "python -m pip install python-docx")

        doc = Document(str(path))
        blocks = []
        for idx, paragraph in enumerate(doc.paragraphs, start=1):
            txt = paragraph.text.strip()
            if txt:
                blocks.append(
                    {
                        "text": txt,
                        "provenance": self._prov(
                            item,
                            locator={"type": "paragraph", "number": idx},
                        ),
                    }
                )
        return self._source_record(item, "docx", blocks=blocks, assets=[])

    def _read_pdf(self, item: dict[str, Any], path: Path) -> dict[str, Any]:
        try:
            import fitz  # PyMuPDF
        except ImportError:  # pragma: no cover
            _require_package("PyMuPDF", "python -m pip install pymupdf")

        asset_dir = self.output_dir / "authentic-assets" / item["source_id"]
        asset_dir.mkdir(parents=True, exist_ok=True)

        blocks: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []

        doc = fitz.open(str(path))
        try:
            for page_index in range(len(doc)):
                page = doc[page_index]
                page_no = page_index + 1
                text = page.get_text("text") or ""
                if text.strip():
                    blocks.append(
                        {
                            "text": text.strip(),
                            "provenance": self._prov(
                                item,
                                locator={"type": "page", "page": page_no},
                            ),
                        }
                    )

                # Preserve the page as one complete visual record. Extracting
                # only embedded image objects can omit the vector geometry,
                # room labels, unit numbers and dimensions that make a plan
                # authoritative. A failed full-page rendition is a hard READ
                # failure: later departments must never receive a partial plan
                # as though it were complete.
                try:
                    pixmap = page.get_pixmap(dpi=300, alpha=True)
                    page_data = pixmap.tobytes("png")
                except Exception as error:
                    raise Department1Error(
                        f"Unable to preserve complete PDF page {page_no} "
                        f"from {item['relative_path']}: {error}"
                    ) from error
                page_filename = f"page-{page_no:04d}-complete.png"
                page_out = asset_dir / page_filename
                page_out.write_bytes(page_data)
                page_hash = _sha256_bytes(page_data)
                assets.append(
                    {
                        "asset_id": self._asset_id(
                            item["source_id"], page_no, 0, page_hash
                        ),
                        "project": self.project_name,
                        "source_id": item["source_id"],
                        "kind": "pdf_page_render",
                        "path": str(page_out),
                        "sha256": page_hash,
                        "source_document_sha256": item["sha256"],
                        "mime_type": "image/png",
                        "authenticity": "source_rendered_complete_page",
                        "contains_entire_page": True,
                        "render_dpi": 300,
                        "extraction_fidelity": "complete_page_render",
                        "plan_preservation_candidate": True,
                        "provenance": self._prov(
                            item,
                            locator={
                                "type": "pdf_page_render",
                                "page": page_no,
                                "render_dpi": 300,
                                "contains_entire_page": True,
                            },
                        ),
                    }
                )

                for image_no, img in enumerate(page.get_images(full=True), start=1):
                    xref = img[0]
                    raw = doc.extract_image(xref)
                    ext = raw.get("ext", "bin")
                    data = raw["image"]
                    filename = f"page-{page_no:04d}-image-{image_no:03d}.{ext}"
                    out = asset_dir / filename
                    out.write_bytes(data)
                    assets.append(
                        {
                            "asset_id": self._asset_id(
                                item["source_id"], page_no, image_no, _sha256_bytes(data)
                            ),
                            "project": self.project_name,
                            "source_id": item["source_id"],
                            "kind": "embedded_pdf_image",
                            "path": str(out),
                            "sha256": _sha256_bytes(data),
                            "source_document_sha256": item["sha256"],
                            "mime_type": mimetypes.guess_type(filename)[0]
                            or "application/octet-stream",
                            "authenticity": "source_extracted",
                            "provenance": self._prov(
                                item,
                                locator={
                                    "type": "pdf_embedded_image",
                                    "page": page_no,
                                    "image_number": image_no,
                                },
                            ),
                        }
                    )
        finally:
            doc.close()

        return self._source_record(item, "pdf", blocks=blocks, assets=assets)

    def _read_image(self, item: dict[str, Any], path: Path) -> dict[str, Any]:
        asset = {
            "asset_id": self._asset_id(item["source_id"], 0, 0, item["sha256"]),
            "project": self.project_name,
            "source_id": item["source_id"],
            "kind": "source_image",
            "path": str(path),
            "sha256": item["sha256"],
            "source_document_sha256": item["sha256"],
            "mime_type": item["mime_type"],
            "authenticity": "original_source_file",
            "provenance": self._prov(
                item, locator={"type": "whole_file"}
            ),
        }
        return self._source_record(item, "image", blocks=[], assets=[asset])

    # ------------------------------------------------------------------
    # 3. UNDERSTAND
    # ------------------------------------------------------------------

    def understand_stage(self, read_package: dict[str, Any]) -> dict[str, Any]:
        payload = self._ai_json(
            stage="UNDERSTAND",
            instructions=self._understand_instructions(),
            evidence=self._compact_evidence(read_package, include_images=True),
        )
        result = self._wrap_ai_stage("UNDERSTAND", payload)
        _atomic_json(self.output_dir / "03-understand.json", result)
        return result

    # ------------------------------------------------------------------
    # 4. ANALYZE
    # ------------------------------------------------------------------

    def analyze_stage(
        self, read_package: dict[str, Any], understanding: dict[str, Any]
    ) -> dict[str, Any]:
        payload = self._ai_json(
            stage="ANALYZE",
            instructions=self._analyze_instructions(),
            evidence={
                "project": self.project_name,
                "understanding": understanding["result"],
                "source_evidence": self._compact_evidence(
                    read_package, include_images=False
                ),
            },
        )
        result = self._wrap_ai_stage("ANALYZE", payload)
        _atomic_json(self.output_dir / "04-analyze.json", result)
        return result

    # ------------------------------------------------------------------
    # 5. CLASSIFY
    # ------------------------------------------------------------------

    def classify_stage(
        self,
        read_package: dict[str, Any],
        understanding: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._ai_json(
            stage="CLASSIFY",
            instructions=self._classify_instructions(),
            evidence={
                "project": self.project_name,
                "understanding": understanding["result"],
                "analysis": analysis["result"],
                "source_evidence": self._compact_evidence(
                    read_package, include_images=True
                ),
            },
        )
        result = self._wrap_ai_stage("CLASSIFY", payload)
        _atomic_json(self.output_dir / "05-classify.json", result)
        return result

    # ------------------------------------------------------------------
    # 6. EXTRACT
    # ------------------------------------------------------------------

    def extract_stage(
        self,
        read_package: dict[str, Any],
        understanding: dict[str, Any],
        analysis: dict[str, Any],
        classification: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._ai_json(
            stage="EXTRACT",
            instructions=self._extract_instructions(),
            evidence={
                "project": self.project_name,
                "understanding": understanding["result"],
                "analysis": analysis["result"],
                "classification": classification["result"],
                "source_evidence": self._compact_evidence(
                    read_package, include_images=False
                ),
            },
        )
        result = self._wrap_ai_stage("EXTRACT", payload)
        _atomic_json(self.output_dir / "06-extract.json", result)
        return result

    # ------------------------------------------------------------------
    # D2 HANDOFF
    # ------------------------------------------------------------------

    def build_department2_handoff(
        self,
        input_manifest: dict[str, Any],
        read_package: dict[str, Any],
        understanding: dict[str, Any],
        analysis: dict[str, Any],
        classification: dict[str, Any],
        extracted: dict[str, Any],
    ) -> dict[str, Any]:
        assets = [
            asset
            for source in read_package["sources"]
            for asset in source.get("assets", [])
        ]
        source_hashes = {
            item["relative_path"]: item["sha256"] for item in input_manifest["files"]
        }

        handoff = {
            "contract_role": "department1_to_department2",
            "contract_version": DEPARTMENT1_CONTRACT_VERSION,
            "project": self.project_name,
            "project_slug": self.project_slug,
            "created_at": _utc_now(),
            "pipeline_completed": [
                "INPUT",
                "READ",
                "UNDERSTAND",
                "ANALYZE",
                "CLASSIFY",
                "EXTRACT",
            ],
            "source_hashes": source_hashes,
            # Department 2 consumes these provenance-preserving READ records as
            # its sole textual evidence contract. It must not independently
            # re-extract the original documents into a competing truth path.
            "sources": read_package["sources"],
            "understanding": understanding["result"],
            "analysis": analysis["result"],
            "classification": classification["result"],
            "extracted_intelligence": extracted["result"],
            "authentic_assets": assets,
            "controls": {
                "project_isolation": "enforced",
                "provenance": "required",
                "asset_authenticity": "source_only",
                "hallucinated_facts": "forbidden",
                "unsupported_commercial_claims": "forbidden",
                "missing_evidence_behavior": "fail_closed_or_mark_unknown",
            },
        }
        handoff["handoff_sha256"] = _sha256_bytes(
            json.dumps(handoff, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        return handoff

    def validate_handoff(self, handoff: dict[str, Any]) -> None:
        if handoff.get("project") != self.project_name:
            raise Department1Error("Department 1 handoff project mismatch.")

        if handoff.get("pipeline_completed") != [
            "INPUT", "READ", "UNDERSTAND", "ANALYZE", "CLASSIFY", "EXTRACT"
        ]:
            raise Department1Error("Department 1 cognition chain is incomplete.")

        for asset in handoff.get("authentic_assets", []):
            if asset.get("project") != self.project_name:
                raise Department1Error(
                    f"Foreign asset detected: {asset.get('asset_id')}"
                )
            if asset.get("authenticity") not in {
                "source_extracted", "source_rendered_complete_page",
                "original_source_file"
            }:
                raise Department1Error(
                    f"Non-authentic asset detected: {asset.get('asset_id')}"
                )
            if not asset.get("provenance"):
                raise Department1Error(
                    f"Asset without provenance: {asset.get('asset_id')}"
                )

        extracted = handoff.get("extracted_intelligence")
        if not isinstance(extracted, dict):
            raise Department1Error("EXTRACT stage did not return a structured object.")

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if not self.config.allow_external_ai:
            raise Department1Error(
                "Department 1 AI cognition is disabled. "
                "Set D1_ALLOW_EXTERNAL_AI=true after approving external processing."
            )
        if self.client is not None:
            return self.client
        if OpenAI is None:
            _require_package("openai", "python -m pip install openai")
        if not os.getenv("OPENAI_API_KEY"):
            raise Department1Error("OPENAI_API_KEY is not configured.")
        self.client = OpenAI()
        return self.client

    def _ai_json(
        self,
        *,
        stage: str,
        instructions: str,
        evidence: Any,
    ) -> dict[str, Any]:
        client = self._get_client()
        evidence_json = json.dumps(evidence, ensure_ascii=False)
        if len(evidence_json) > self.config.max_text_chars_per_call:
            evidence_json = evidence_json[: self.config.max_text_chars_per_call]

        response = client.responses.create(
            model=self.config.model,
            instructions=instructions,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"ACTIVE PROJECT: {self.project_name}\n"
                                f"DEPARTMENT 1 STAGE: {stage}\n\n"
                                "Use only the supplied project evidence. "
                                "Never import knowledge from another project.\n\n"
                                "OUTPUT CONTRACT: Return exactly one JSON object "
                                "with these keys: project, stage, summary, data, "
                                "unknowns, warnings. summary must be a plain string, "
                                "never an object, array, number, or null. "
                                "The data field must be a JSON "
                                "object, not a string. unknowns and warnings must "
                                "be arrays of strings. Preserve unsupported "
                                "information as unknown; never invent values.\n\n"
                                f"EVIDENCE:\n{evidence_json}"
                            ),
                        }
                    ],
                }
            ],
            text={"format": {"type": "json_object"}},
        )

        raw = getattr(response, "output_text", None)
        if not raw:
            raise Department1Error(f"{stage} produced no output.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Department1Error(f"{stage} returned invalid JSON: {exc}") from exc

        # Validate everything except summary before requesting a bounded repair.
        # A repair may change only summary, never evidence or project identity.
        if isinstance(parsed, dict) and "summary" in parsed and not isinstance(parsed["summary"], str):
            self._validate_stage_payload(stage, {**parsed, "summary": ""})
            repair = client.responses.create(
                model=self.config.model,
                instructions=("Convert the supplied stage summary into a concise plain-text "
                              "summary using only its contents. Do not add facts. "
                              "Return only a JSON object with a string summary field."),
                input=json.dumps({"project": self.project_name, "stage": stage,
                                  "summary": parsed["summary"]}, ensure_ascii=False),
                text={"format": {"type": "json_schema", "name": "stage_summary_repair",
                                 "strict": True, "schema": {
                                     "type": "object", "properties": {"summary": {"type": "string"}},
                                     "required": ["summary"], "additionalProperties": False}}},
            )
            try:
                fixed = json.loads(getattr(repair, "output_text", None) or "")
            except (TypeError, json.JSONDecodeError) as exc:
                raise Department1Error(f"{stage} summary repair returned invalid JSON.") from exc
            if not isinstance(fixed, dict) or set(fixed) != {"summary"} or not isinstance(fixed["summary"], str):
                raise Department1Error(f"{stage} summary repair must contain only a string summary.")
            parsed = {**parsed, "summary": fixed["summary"]}
        self._validate_stage_payload(stage, parsed)
        return parsed

    def _validate_stage_payload(self, stage: str, parsed: Any) -> None:
        if not isinstance(parsed, dict):
            raise Department1Error(f"{stage} output must be a JSON object.")

        required = {"project", "stage", "summary", "data", "unknowns", "warnings"}
        actual = set(parsed)
        if actual != required:
            missing = sorted(required - actual)
            unexpected = sorted(actual - required)
            raise Department1Error(
                f"{stage} output contract mismatch; missing={missing}, "
                f"unexpected={unexpected}."
            )
        if parsed["project"] != self.project_name:
            raise Department1Error(
                f"{stage} project identity mismatch: {parsed['project']!r}"
            )
        if parsed["stage"] != stage:
            raise Department1Error(
                f"{stage} stage identity mismatch: {parsed['stage']!r}"
            )
        if not isinstance(parsed["summary"], str):
            raise Department1Error(f"{stage} summary must be a string.")
        if not isinstance(parsed["data"], dict):
            raise Department1Error(f"{stage} data field must be a JSON object.")
        for field in ("unknowns", "warnings"):
            value = parsed[field]
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise Department1Error(
                    f"{stage} {field} field must be an array of strings."
                )

    def _wrap_ai_stage(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "stage": stage,
            "contract_version": DEPARTMENT1_CONTRACT_VERSION,
            "project": self.project_name,
            "created_at": _utc_now(),
            "result": payload,
        }

    # ------------------------------------------------------------------
    # Stage cognition instructions
    # ------------------------------------------------------------------

    def _understand_instructions(self) -> str:
        return """
You are Department 1 UNDERSTAND for a professional autonomous real-estate
marketing system.

Question: "What am I looking at, and what does it mean?"

Understand the supplied project evidence before trying to market it.
Identify document purpose, project context, real-estate terminology,
relationships between files/pages/images, languages, likely developer/project
identity, property type, location context, plan/map/render meaning, and what
information appears commercial versus descriptive.

Rules:
- Uploaded source evidence is the only source of truth.
- Do not infer missing prices, areas, distances, availability, ROI or payment terms.
- Do not convert assumptions into facts.
- Preserve uncertainty explicitly.
- A folder/project namespace is authoritative for project isolation.
- Distinguish project identity from developer/brand identity.
- Treat floor plans, unit layouts, site plans and masterplans as different objects.
- Never market, rank or write captions in this stage.
Return structured JSON only.
""".strip()

    def _analyze_instructions(self) -> str:
        return """
You are Department 1 ANALYZE for a professional real-estate brokerage agent.

Question: "What can I reliably conclude from this evidence, how do the pieces
relate, what conflicts exist, and what is useful downstream?"

Analyze the already-understood evidence deeply. Establish relationships across
documents and pages; detect duplicates, contradictions, stale-versus-current
commercial material, project/developer/location relationships, unit-to-layout
relationships, floor-plan hierarchy, visual-to-topic relationships, amenities,
lifestyle evidence, investor-relevant evidence, and missing information.

Rules:
- Never resolve a contradiction by guessing.
- Commercial information must carry evidence and conflict status.
- Unit area must never be attached to a layout without evidence of that relationship.
- Images are evidence, not permission to invent unseen facts.
- Separate observed facts from interpretations.
- Mark dangerous ambiguity REVIEW_REQUIRED or UNKNOWN.
- Do not write marketing copy.
Return structured JSON only.
""".strip()

    def _classify_instructions(self) -> str:
        return """
You are Department 1 CLASSIFY.

Classify every meaningful source type and evidence type so later departments can
reason deterministically.

Real-estate document classes may include:
catalogue, brochure, price_list, payment_plan, availability_list, project_notes,
legal_or_disclaimer, specification, location_material, masterplan_document,
floorplan_document, unit_schedule, mixed_document, unknown.

Visual classes may include:
masterplan, site_plan, location_map, exterior_render, exterior_photo,
interior_render, interior_photo, amenity, landscape, lifestyle,
unit_layout, apartment_layout, office_layout, villa_layout,
floor_plan, typical_floor_plan, master_floor_plan, technical_plan,
commercial_unit_plan, logo_or_brand_asset, decorative_graphic, unknown.

Also classify evidence into:
identity, developer, project_type, location, architecture, unit,
amenity, specification, commercial, payment, availability, layout_relationship,
floor_relationship, legal_restriction, lifestyle, investor, unknown.

Rules:
- Do not change project identity.
- Do not promote ambiguous plan relationships to VERIFIED.
- Classification does not create facts.
- Unknown is preferable to an unsupported confident label.
Return structured JSON only.
""".strip()

    def _extract_instructions(self) -> str:
        return """
You are Department 1 EXTRACT.

Convert the understood, analyzed and classified project evidence into a clean,
machine-readable evidence package for Department 2.

Extract only source-supported information. Organize it for real-estate reasoning,
including where present:
project identity, developer identity, project type, location facts, architecture,
units, areas, bedrooms, bathrooms, offices/commercial uses, amenities,
specifications, payment terms, prices, availability, plan relationships,
masterplan/site-plan relationships, legal/disclaimer text, and visual evidence.

Every extracted claim must distinguish:
- directly supported
- uncertain
- conflicting
- unknown

Never calculate or invent:
ROI, yield, appreciation, distance, travel time, scarcity, availability, price,
discount, area, payment term, completion date, or unit-layout relationship unless
the supplied evidence supports it.

Department 2 will normalize and adjudicate truth. Department 1's job is complete,
faithful evidence extraction — not marketing and not unsupported conflict
resolution.
Return structured JSON only.
""".strip()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compact_evidence(
        self, read_package: dict[str, Any], *, include_images: bool
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "project": self.project_name,
            "sources": [],
        }
        for source in read_package["sources"]:
            out = {
                "source_id": source["source_id"],
                "project": source["project"],
                "relative_path": source["relative_path"],
                "source_type": source["source_type"],
                "sha256": source["sha256"],
                "blocks": source["blocks"],
            }
            if include_images:
                out["assets"] = [
                    {
                        "asset_id": a["asset_id"],
                        "kind": a["kind"],
                        "path": a["path"],
                        "mime_type": a["mime_type"],
                        "authenticity": a["authenticity"],
                        "sha256": a["sha256"],
                        "source_document_sha256": a.get("source_document_sha256"),
                        "contains_entire_page": a.get("contains_entire_page", False),
                        "render_dpi": a.get("render_dpi"),
                        "extraction_fidelity": a.get("extraction_fidelity"),
                        "provenance": a["provenance"],
                    }
                    for a in source.get("assets", [])
                ]
            result["sources"].append(out)
        return result

    def _source_record(
        self,
        item: dict[str, Any],
        source_type: str,
        *,
        blocks: list[dict[str, Any]],
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "source_id": item["source_id"],
            "project": self.project_name,
            "relative_path": item["relative_path"],
            "source_type": source_type,
            "mime_type": item["mime_type"],
            "sha256": item["sha256"],
            "blocks": blocks,
            "assets": assets,
        }

    def _prov(
        self, item: dict[str, Any], *, locator: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "project": self.project_name,
            "source_id": item["source_id"],
            "source_file": item["relative_path"],
            "source_sha256": item["sha256"],
            "locator": locator,
        }

    def _assert_project(self, source: dict[str, Any]) -> None:
        if source.get("project") != self.project_name:
            raise Department1Error(
                f"Cross-project contamination detected in {source.get('relative_path')}"
            )

    @staticmethod
    def _source_id(relative_path: str, sha256: str) -> str:
        raw = f"{relative_path}\0{sha256}".encode("utf-8")
        return "src_" + hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def _asset_id(
        source_id: str, page: int, image_number: int, sha256: str
    ) -> str:
        raw = f"{source_id}:{page}:{image_number}:{sha256}".encode("utf-8")
        return "asset_" + hashlib.sha256(raw).hexdigest()[:16]
