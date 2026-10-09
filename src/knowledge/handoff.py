from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.department1.pipeline import DEPARTMENT1_CONTRACT_VERSION


class Department2HandoffError(RuntimeError):
    """Raised when the Department 1 -> Department 2 contract is unsafe."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _payload_hash(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("handoff_sha256", None)
    return hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class Department2EvidenceSource:
    source_id: str
    project: str
    relative_path: str
    source_type: str
    sha256: str
    blocks: tuple[dict[str, Any], ...]

    @property
    def filename(self) -> str:
        return Path(self.relative_path).name

    def text(self) -> str:
        return "\n\n".join(
            str(block.get("text") or "").strip()
            for block in self.blocks
            if str(block.get("text") or "").strip()
        )

    def markdown(self) -> str:
        """Render preserved D1 evidence without re-reading the original document."""
        out = [f"# Source: {self.relative_path}", f"Project: {self.project}", ""]
        for block in self.blocks:
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            provenance = block.get("provenance") or {}
            locator = provenance.get("locator") or {}
            kind = locator.get("type")
            if kind == "page" and locator.get("page") is not None:
                out.extend([f"## Page {int(locator['page'])}", "", text, ""])
            elif kind == "line":
                start = locator.get("start")
                end = locator.get("end", start)
                out.extend([f"## Lines {start}-{end}", "", text, ""])
            elif kind == "paragraph":
                out.extend([f"## Paragraph {locator.get('number')}", "", text, ""])
            else:
                out.extend(["## Evidence", "", text, ""])
        return "\n".join(out).strip() + "\n"


@dataclass(frozen=True)
class Department2Handoff:
    path: Path
    project: str
    project_slug: str
    handoff_sha256: str
    source_hashes: dict[str, str]
    sources: tuple[Department2EvidenceSource, ...]
    payload: dict[str, Any]


def load_department2_handoff(
    path: str | Path,
    *,
    expected_project: str,
    project_root: str | Path | None = None,
    verify_source_hashes: bool = True,
    source_paths: tuple[Path, ...] | list[Path] | None = None,
) -> Department2Handoff:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Department2HandoffError(f"Cannot read Department 1 handoff: {exc}") from exc

    if payload.get("contract_role") != "department1_to_department2":
        raise Department2HandoffError("Invalid Department 1 handoff role.")
    if payload.get("contract_version") != DEPARTMENT1_CONTRACT_VERSION:
        raise Department2HandoffError(
            f"Unsupported Department 1 contract version: {payload.get('contract_version')!r}"
        )
    if payload.get("project") != expected_project:
        raise Department2HandoffError(
            f"Department 1 handoff project mismatch: {payload.get('project')!r} != {expected_project!r}"
        )

    expected_hash = str(payload.get("handoff_sha256") or "")
    actual_hash = _payload_hash(payload)
    if not expected_hash or expected_hash != actual_hash:
        raise Department2HandoffError("Department 1 handoff integrity hash mismatch.")

    source_hashes = payload.get("source_hashes")
    sources_raw = payload.get("sources")
    if not isinstance(source_hashes, dict) or not isinstance(sources_raw, list) or not source_hashes or not sources_raw:
        raise Department2HandoffError("Department 1 handoff lacks source evidence contract.")

    seen: set[str] = set()
    seen_paths: set[str] = set()
    sources: list[Department2EvidenceSource] = []
    for raw in sources_raw:
        if not isinstance(raw, dict):
            raise Department2HandoffError("Malformed Department 1 source record.")
        if raw.get("project") != expected_project:
            raise Department2HandoffError(
                f"Cross-project evidence rejected: {raw.get('relative_path')!r}"
            )
        source_id = str(raw.get("source_id") or "")
        relative_path = str(raw.get("relative_path") or "")
        sha256 = str(raw.get("sha256") or "")
        blocks = raw.get("blocks")
        if not source_id or source_id in seen or not relative_path or relative_path in seen_paths or not sha256:
            raise Department2HandoffError("Malformed or duplicate Department 1 source identity.")
        if not isinstance(blocks, list):
            raise Department2HandoffError(f"Source {relative_path!r} has invalid evidence blocks.")
        if source_hashes.get(relative_path) != sha256:
            raise Department2HandoffError(
                f"Source hash contract mismatch for {relative_path!r}."
            )
        for block in blocks:
            provenance = block.get("provenance") if isinstance(block, dict) else None
            if not isinstance(provenance, dict):
                raise Department2HandoffError(f"Evidence without provenance in {relative_path!r}.")
            if provenance.get("project") != expected_project:
                raise Department2HandoffError(f"Foreign provenance in {relative_path!r}.")
            if provenance.get("source_id") != source_id:
                raise Department2HandoffError(f"Evidence source_id mismatch in {relative_path!r}.")
            if provenance.get("source_sha256") != sha256:
                raise Department2HandoffError(f"Evidence source hash mismatch in {relative_path!r}.")
            if provenance.get("source_file") != relative_path:
                raise Department2HandoffError(f"Evidence source path mismatch in {relative_path!r}.")
        seen.add(source_id)
        seen_paths.add(relative_path)
        sources.append(
            Department2EvidenceSource(
                source_id=source_id,
                project=expected_project,
                relative_path=relative_path,
                source_type=str(raw.get("source_type") or ""),
                sha256=sha256,
                blocks=tuple(blocks),
            )
        )

    if seen_paths != set(source_hashes):
        raise Department2HandoffError("Source records and hash inventory differ.")

    if source_paths is not None:
        if project_root is None:
            raise Department2HandoffError("project_root is required for source inventory verification.")
        root = Path(project_root).resolve()
        try:
            current = {Path(p).resolve().relative_to(root).as_posix() for p in source_paths}
        except ValueError as exc:
            raise Department2HandoffError("Current source inventory escapes project root.") from exc
        if current != seen_paths:
            raise Department2HandoffError("Department 1 source inventory changed after handoff.")

    if verify_source_hashes:
        if project_root is None:
            raise Department2HandoffError("project_root is required for source hash verification.")
        root = Path(project_root).resolve()
        for relative_path, expected in source_hashes.items():
            candidate = (root / relative_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise Department2HandoffError(
                    f"Unsafe source path in handoff: {relative_path!r}"
                ) from exc
            if not candidate.is_file():
                raise Department2HandoffError(f"Department 1 source is missing: {relative_path!r}")
            if _sha256_file(candidate) != expected:
                raise Department2HandoffError(
                    f"Department 1 source changed after handoff: {relative_path!r}"
                )

    return Department2Handoff(
        path=path,
        project=expected_project,
        project_slug=str(payload.get("project_slug") or ""),
        handoff_sha256=expected_hash,
        source_hashes={str(k): str(v) for k, v in source_hashes.items()},
        sources=tuple(sources),
        payload=payload,
    )


def write_source_markdown(source: Department2EvidenceSource, output_directory: str | Path) -> Path:
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    safe = re_sub_filename(Path(source.relative_path).stem)
    path = output_directory / f"{safe}-{source.source_id}.md"
    path.write_text(source.markdown(), encoding="utf-8")
    return path


def re_sub_filename(value: str) -> str:
    import re
    value = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", "-", value).strip(" .-")
    return value or "source"
