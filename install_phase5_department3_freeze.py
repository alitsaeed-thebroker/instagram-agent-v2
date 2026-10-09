from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd().resolve()

REQUIRED = (
    "src/department3/phase5_freeze_certification.py",
    "run_department3_phase5_freeze_certification.py",
    "verify_phase5_department3_freeze.py",
    "tests/test_department3_phase5_authority.py",
    "tests/test_department3_phase5_provenance.py",
    "tests/test_department3_phase5_strategy_quality.py",
    "tests/test_department3_phase5_plan_integrity.py",
    "tests/test_department3_phase5_boundary.py",
    "tests/test_department3_phase5_freeze.py",
)

if __name__ == "__main__":
    missing = [rel for rel in REQUIRED if not (ROOT / rel).is_file()]
    if missing:
        raise SystemExit(f"Phase 5 package incomplete: missing={missing}")

    for rel in REQUIRED:
        path = ROOT / rel
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    out = ROOT / "output" / "backups" / "department3-phase5"
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": "department3.phase5.install.v1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "production_files_modified": 0,
        "package_files_verified": list(REQUIRED),
    }

    (out / "install-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    print("Department 3 Phase 5 freeze certification installer: PASS")
    print("- Package files verified")
    print("- Python syntax verified")
    print("- Production files modified: 0")
    print(f"- Install manifest: {out / 'install-manifest.json'}")
