"""Input and output file management helpers."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
import hashlib
import re

from pypdf import PdfReader


WORKSPACE_RESOURCE_DIRECTORIES = frozenset({"brand", "publishing", "visual-review", "campaigns", "creative-direction", "editorial-copy"})


@dataclass(frozen=True)
class ProjectInput:
    """One project and the PDFs supplied for it."""

    name: str
    pdf_files: list[Path]
    image_files: list[Path] = field(default_factory=list)
    auxiliary_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def find_pdf_files(input_directory: Path) -> list[Path]:
    """Return PDFs in content-digest order; filenames carry no priority."""
    if not input_directory.exists():
        raise FileNotFoundError(f"Input folder not found: {input_directory}")
    if not input_directory.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {input_directory}")
    return sorted(
        (item for item in input_directory.iterdir() if item.is_file() and item.suffix.casefold() == ".pdf"),
        key=_content_sort_key,
    )


def find_project_inputs(input_directory: Path) -> list[ProjectInput]:
    """Group project-source files without importing workspace configuration."""
    if not input_directory.exists():
        raise FileNotFoundError(f"Input folder not found: {input_directory}")
    if not input_directory.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {input_directory}")

    pdfs = sorted(
        (
            item for item in input_directory.rglob("*")
            if item.is_file()
            and not _is_workspace_resource(item, input_directory)
            and item.suffix.casefold() == ".pdf"
        ),
        key=_content_sort_key,
    )
    images = sorted(
        (
            item for item in input_directory.rglob("*")
            if item.is_file()
            and not _is_workspace_resource(item, input_directory)
            and item.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}
        ),
        key=_content_sort_key,
    )
    auxiliary = sorted(
        (
            item for item in input_directory.rglob("*")
            if item.is_file()
            and not _is_workspace_resource(item, input_directory)
            and item.suffix.casefold() in {".docx", ".txt"}
        ),
        key=_content_sort_key,
    )
    # A real project folder is the stable namespace boundary.  Extracted PDF
    # text is descriptive identity, never authority over filesystem isolation.
    folder_projects=[];root_pdfs=[];root_images=[];root_aux=[]
    folders=sorted({p.relative_to(input_directory).parts[0] for p in [*pdfs,*images,*auxiliary] if len(p.relative_to(input_directory).parts)>1})
    for folder in folders:
        base=input_directory/folder;local_pdfs=[p for p in pdfs if p.is_relative_to(base)];local_images=[p for p in images if p.is_relative_to(base)];local_aux=[p for p in auxiliary if p.is_relative_to(base)]
        if local_pdfs or local_images or local_aux:folder_projects.append(ProjectInput(folder,local_pdfs,local_images,local_aux))
    root_pdfs=[p for p in pdfs if p.parent==input_directory];root_images=[p for p in images if p.parent==input_directory];root_aux=[p for p in auxiliary if p.parent==input_directory]
    legacy,_=_group_by_content_identity(root_pdfs,root_images,1,root_aux)
    return [*folder_projects,*legacy]


def find_image_files(input_directory: Path) -> list[Path]:
    """Return approved standalone images without filename-based priority."""
    extensions = {".png", ".jpg", ".jpeg", ".webp"}
    return sorted(
        (item for item in input_directory.iterdir() if item.is_file() and item.suffix.casefold() in extensions),
        key=_content_sort_key,
    )


def _is_workspace_resource(path: Path, input_directory: Path) -> bool:
    """Return whether a path belongs to persistent workspace configuration."""
    try:
        relative = path.relative_to(input_directory)
    except ValueError:
        return False
    return bool(relative.parts and relative.parts[0].casefold() in WORKSPACE_RESOURCE_DIRECTORIES)


def _group_by_content_identity(
    pdfs: list[Path], images: list[Path], candidate_index: int,
    auxiliary: list[Path] | None = None,
) -> tuple[list[ProjectInput], int]:
    auxiliary = auxiliary or []
    groups: dict[str, list[Path]] = {}
    directory_identities: dict[Path, set[str]] = {}
    unknown: list[Path] = []
    for pdf in pdfs:
        identity = _project_identity_from_pdf(pdf)
        if identity:
            groups.setdefault(identity, []).append(pdf)
            directory_identities.setdefault(pdf.parent, set()).add(identity)
        else:
            unknown.append(pdf)
    assigned_images: dict[str, list[Path]] = {identity: [] for identity in groups}
    assigned_auxiliary: dict[str, list[Path]] = {identity: [] for identity in groups}
    unassigned_images: list[Path] = []
    unassigned_auxiliary: list[Path] = []
    for path, target, unassigned in (
        *((path, assigned_images, unassigned_images) for path in images),
        *((path, assigned_auxiliary, unassigned_auxiliary) for path in auxiliary),
    ):
        identities = directory_identities.get(path.parent, set())
        if len(identities) == 1:
            target[next(iter(identities))].append(path)
        else:
            unassigned.append(path)
    projects = [
        ProjectInput(identity, files, assigned_images[identity], assigned_auxiliary[identity])
        for identity, files in groups.items()
    ]
    warnings: list[str] = []
    if len(projects) == 1:
        projects[0] = ProjectInput(
            projects[0].name, projects[0].pdf_files, images, auxiliary, projects[0].warnings
        )
    elif unassigned_images or unassigned_auxiliary:
        warnings.append("Approved images could not be assigned unambiguously to a content-identified project")
        projects.append(ProjectInput(
            f"project-candidate-{candidate_index:03d}", [], unassigned_images,
            unassigned_auxiliary, warnings,
        )); candidate_index += 1
    for pdf in unknown:
        projects.append(ProjectInput(
            f"project-candidate-{candidate_index:03d}", [pdf], [], [],
            ["Project identity is ambiguous because no reliable content identifier was found"],
        ))
        candidate_index += 1
    if not pdfs and (images or auxiliary) and not projects:
        projects.append(ProjectInput(
            f"project-candidate-{candidate_index:03d}", [], images, auxiliary,
            ["Image-only candidate; project identity requires visual/branding review"],
        ))
        candidate_index += 1
    return projects, candidate_index


def _project_identity_from_pdf(path: Path) -> str | None:
    try:
        reader = PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
    except Exception:
        return None
    for pattern in (
        r"(?im)^\s*(?:project|development|property)\s*(?:name)?\s*[:\-]\s*([^\n]{3,80})$",
        r"(?im)^\s*(?:welcome\s+to|introducing)\s+([^\n]{3,80})$",
    ):
        match = re.search(pattern, text)
        if match:
            return _clean_identity(match.group(1))
    generic = {
        "price list", "payment plan", "floor plans", "master plan", "presentation",
        "brochure", "catalogue", "technical specifications", "location map",
    }
    for line in text.splitlines()[:20]:
        candidate = _clean_identity(line)
        if candidate and candidate.casefold() not in generic and 3 <= len(candidate) <= 80 and len(candidate.split()) <= 8:
            return candidate
    return None


def _clean_identity(value: str) -> str:
    candidate=re.sub(r"\s+", " ", value).strip(" \t:-|")
    return candidate if _valid_inferred_identity(candidate) else ""

def _valid_inferred_identity(value:str)->bool:
    if not value or not re.search(r"[^\W\d_]",value,re.UNICODE):return False
    normalized=re.sub(r"[^\w]+"," ",value,flags=re.UNICODE).strip().casefold()
    if re.fullmatch(r"(?:page\s*)?\d+(?:\s+\d+)*",normalized):return False
    return normalized not in {"contents","content","table of contents","index","catalogue","catalog","brochure","presentation"}


def _content_sort_key(path: Path) -> str:
    """Provide deterministic traversal without giving filenames priority semantics."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
