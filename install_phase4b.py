from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path.cwd().resolve()

FILES = [
    "src/department3/__init__.py",
    "src/department3/advisory.py",
    "src/department3/integration.py",
    "src/department3/legacy_quarantine.py",
    "tests/test_department3_advisory_integration.py",
    "tests/test_department3_legacy_quarantine.py",
    "tests/test_department3_phase4b_contract.py",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not (REPO_ROOT / "app.py").is_file():
        raise SystemExit("Run this from the instagram-agent repository root.")

    required = [
        REPO_ROOT / "src" / "department3" / "authority.py",
        REPO_ROOT / "src" / "department3" / "strategy_authority.py",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit(
            "Phase 4A is required before Phase 4B. Missing: " + ", ".join(missing)
        )

    backup_root = REPO_ROOT / "output" / "backups" / "department3-phase4b"
    backup_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "scope": "additive advisory integration and legacy quarantine",
    }

    for rel in FILES:
        src = PACKAGE_ROOT / rel
        dst = REPO_ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        previous_hash = None
        backup_path = None
        if dst.exists():
            previous_hash = sha(dst)
            backup_path = backup_root / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup_path)

        shutil.copy2(src, dst)
        manifest["files"].append(
            {
                "path": rel,
                "previous_sha256": previous_hash,
                "installed_sha256": sha(dst),
                "backup_path": str(backup_path) if backup_path else None,
            }
        )

    manifest_path = backup_root / "install-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Department 3 Phase 4B installed")
    print(f"- Files installed: {len(FILES)}")
    print(f"- Backup/manifest: {manifest_path}")
    print("- Existing creative_intelligence, campaign_intelligence and D4 production files were not overwritten.")


if __name__ == "__main__":
    main()
