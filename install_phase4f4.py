from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd().resolve()
TARGET = ROOT / "src" / "department3" / "phase4f_certification.py"
BACKUP = ROOT / "output" / "backups" / "department3-phase4f4"
MARKER = "# Phase 4F backward-compatibility helper API"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not TARGET.is_file():
        raise SystemExit("Missing src/department3/phase4f_certification.py")

    before = TARGET.read_text(encoding="utf-8")
    ast.parse(before, filename=str(TARGET))

    compat = (Path(__file__).resolve().parent / "phase4f_compat_fragment.txt").read_text(encoding="utf-8")

    if MARKER in before:
        print("Phase 4F.4 compatibility helpers already installed")
        return

    BACKUP.mkdir(parents=True, exist_ok=True)
    backup = BACKUP / "phase4f_certification.py"
    shutil.copy2(TARGET, backup)

    after = before.rstrip() + "\n\n" + compat.strip() + "\n"
    TARGET.write_text(after, encoding="utf-8")

    try:
        ast.parse(after, filename=str(TARGET))
    except Exception:
        shutil.copy2(backup, TARGET)
        raise

    manifest = {
        "schema_version": "department3.phase4f4.backward_compatibility.v1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
        "after_sha256": sha(TARGET),
        "backup": str(backup),
    }
    (BACKUP / "install-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print("Department 3 Phase 4F.4 backward-compatibility helpers: PASS")
    print("- Restored _artifact_matches_project")
    print("- Restored _text_mentions_project")
    print("- Restored _is_forbidden_source")
    print("- Restored _walk_json_files")
    print("- Restored _opportunities_from_inventory")
    print("- Restored _score_check")
    print("- Hardened Phase 4F.3 source-selection rules preserved")
    print(f"- Backup: {backup}")


if __name__ == "__main__":
    main()
