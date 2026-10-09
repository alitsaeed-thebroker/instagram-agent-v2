from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd().resolve()
APP = ROOT / "app.py"
STAGES = ROOT / "src" / "execution" / "stages.py"
BACKUP = ROOT / "output" / "backups" / "department3-phase4c"

REQUIRED_FILES = [
    ROOT / "src" / "department3" / "authority.py",
    ROOT / "src" / "department3" / "strategy_authority.py",
    ROOT / "src" / "department3" / "advisory.py",
    ROOT / "src" / "department3" / "integration.py",
]

IMPORT_LINE = (
    "from src.department3.live_orchestration import "
    "LiveDepartment3Orchestrator, quarantine_legacy_result\n"
)
GUARD_IMPORT = (
    "from src.department3.runtime_guard import assert_noncanonical_output\n"
)

KNOWN_ADVISORY_IMPORT_TOKENS = (
    "src.creative_intelligence",
    "src.campaign_intelligence",
)
KNOWN_CANONICAL_TOKENS = (
    "src.creative.visual_art_director",
    "src.creative.visual_direction",
)
KNOWN_LEGACY_TOKENS = (
    "content_planner",
    "creative_director_agent",
    "marketing_strategy_agent",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f"Refusing Phase 4C patch: cannot parse {path}: {exc}")


def module_imports(tree: ast.AST) -> set[str]:
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.add(node.module or "")
    return result


def inject_imports(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False
    additions = []
    if "from src.department3.live_orchestration import" not in text:
        additions.append(IMPORT_LINE)
    if "from src.department3.runtime_guard import" not in text:
        additions.append(GUARD_IMPORT)
    if not additions:
        return False

    lines = text.splitlines(True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    while insert_at < len(lines) and (
        lines[insert_at].startswith("#")
        or not lines[insert_at].strip()
        or lines[insert_at].startswith("from __future__ import")
    ):
        insert_at += 1
    lines[insert_at:insert_at] = additions + ["\n"]
    path.write_text("".join(lines), encoding="utf-8")
    return True


def append_live_bridge(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    marker = "# DEPARTMENT3_PHASE4C_LIVE_BRIDGE"
    if marker in text:
        return False

    bridge = r