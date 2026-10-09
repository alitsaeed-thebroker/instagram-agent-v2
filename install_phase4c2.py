from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd().resolve()
TARGETS = [
    ROOT / "app.py",
    ROOT / "src" / "execution" / "stages.py",
]
BACKUP_ROOT = ROOT / "output" / "backups" / "department3-phase4c2"

IMPORTS = [
    "from src.department3.live_orchestration import LiveDepartment3Orchestrator, quarantine_legacy_result\n",
    "from src.department3.runtime_guard import assert_noncanonical_output\n",
]

MARKER = "# DEPARTMENT3_PHASE4C_LIVE_BRIDGE"

BRIDGE = """

# DEPARTMENT3_PHASE4C_LIVE_BRIDGE
# Canonical Department 3 live strategy boundary.
# Advisory engines may contribute intelligence, but only this bridge may convert
# candidates into an Approved Content Plan.
def _department3_canonical_approve(
    *,
    project_id,
    candidates,
    creative_engine=None,
    creative_args=(),
    creative_kwargs=None,
    campaign_engine=None,
    campaign_args=(),
    campaign_kwargs=None,
):
    return LiveDepartment3Orchestrator().approve(
        project_id=project_id,
        candidates=candidates,
        creative_engine=creative_engine,
        creative_args=creative_args,
        creative_kwargs=creative_kwargs or {},
        campaign_engine=campaign_engine,
        campaign_args=campaign_args,
        campaign_kwargs=campaign_kwargs or {},
    )
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def import_insert_index(text: str) -> int:
    tree = ast.parse(text)
    lines = text.splitlines(True)

    # Insert after module docstring and __future__ imports.
    index = 0
    if tree.body:
        first = tree.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            index = getattr(first, "end_lineno", first.lineno)

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("from __future__ import"):
            index += 1
            continue
        break
    return index


def patch(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Missing target: {path}")

    parse(path)
    before = path.read_text(encoding="utf-8")
    text = before

    missing_imports = [imp for imp in IMPORTS if imp.strip() not in text]
    imports_added = 0
    if missing_imports:
        lines = text.splitlines(True)
        idx = import_insert_index(text)
        lines[idx:idx] = missing_imports + ["\n"]
        text = "".join(lines)
        imports_added = len(missing_imports)

    bridge_added = False
    if MARKER not in text:
        text = text.rstrip() + BRIDGE + "\n"
        bridge_added = True

    before_hash = hashlib.sha256(before.encode("utf-8")).hexdigest()

    if text == before:
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "changed": False,
            "imports_added": 0,
            "bridge_added": False,
            "before_sha256": before_hash,
            "after_sha256": before_hash,
            "backup": None,
        }

    backup = BACKUP_ROOT / path.relative_to(ROOT)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)

    path.write_text(text, encoding="utf-8")

    try:
        parse(path)
    except Exception:
        shutil.copy2(backup, path)
        raise

    return {
        "path": path.relative_to(ROOT).as_posix(),
        "changed": True,
        "imports_added": imports_added,
        "bridge_added": bridge_added,
        "before_sha256": before_hash,
        "after_sha256": sha(path),
        "backup": str(backup),
    }


def verify(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parse(path)
    result = {
        "live_import": "from src.department3.live_orchestration import" in text,
        "guard_import": "from src.department3.runtime_guard import" in text,
        "bridge": MARKER in text,
        "bridge_function": "def _department3_canonical_approve(" in text,
    }
    return result


def main() -> None:
    print("Department 3 Phase 4C.2 live bridge installer")
    print(f"- Repository: {ROOT}")

    if not (ROOT / "app.py").is_file():
        raise SystemExit("Run from the instagram-agent repository root.")

    required = [
        ROOT / "src" / "department3" / "live_orchestration.py",
        ROOT / "src" / "department3" / "runtime_guard.py",
        ROOT / "src" / "department3" / "integration.py",
    ]
    missing = [str(x) for x in required if not x.is_file()]
    if missing:
        raise SystemExit(
            "Phase 4C modules are missing. Extract Phase 4C first. Missing: "
            + ", ".join(missing)
        )

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    results = []
    modified = []
    try:
        for target in TARGETS:
            result = patch(target)
            results.append(result)
            if result["changed"]:
                modified.append(result)
            print(
                f"- {result['path']}: changed={result['changed']}, "
                f"imports_added={result['imports_added']}, "
                f"bridge_added={result['bridge_added']}"
            )

        checks = {}
        for target in TARGETS:
            rel = target.relative_to(ROOT).as_posix()
            checks[rel] = verify(target)
            print(f"- verify {rel}: {checks[rel]}")
            if not all(checks[rel].values()):
                raise RuntimeError(f"Verification failed for {rel}")

    except Exception:
        print("Installer failed; restoring files modified in this run.")
        for result in modified:
            backup = result.get("backup")
            if backup:
                shutil.copy2(Path(backup), ROOT / result["path"])
        raise

    manifest = {
        "schema_version": "department3.phase4c2.live_bridge_installer.v1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "verification": checks,
    }
    manifest_path = BACKUP_ROOT / "install-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Department 3 Phase 4C.2: PASS")
    print(f"- Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
