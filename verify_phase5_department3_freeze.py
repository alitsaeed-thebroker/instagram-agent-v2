from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd().resolve()

if __name__ == "__main__":
    required = (
        ROOT / "src" / "department3" / "phase5_freeze_certification.py",
        ROOT / "run_department3_phase5_freeze_certification.py",
        ROOT / "src" / "department3" / "real_estate_brain.py",
        ROOT / "src" / "department3" / "live_orchestration.py",
        ROOT / "src" / "department3" / "runtime_guard.py",
        ROOT / "src" / "department3" / "strategy_authority.py",
        ROOT / "src" / "department3" / "planning_cutover.py",
        ROOT / "src" / "department3" / "legacy_live.py",
    )

    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit(f"Phase 5 verification FAIL: missing={missing}")

    for p in required:
        if p.suffix == ".py":
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))

    cert = (ROOT / "src" / "department3" / "phase5_freeze_certification.py").read_text(encoding="utf-8")
    forbidden = (
        "graph.facebook.com",
        "publish_to_instagram(",
        "requests.post(",
        "httpx.post(",
    )

    if any(token in cert for token in forbidden):
        raise SystemExit("Phase 5 verification FAIL: publishing/network marker found")

    print("Department 3 Phase 5 static verification: PASS")
    print("- Certification runner present")
    print("- Canonical authority modules present")
    print("- Runtime guard present")
    print("- No publishing/network marker in Phase 5 certification code")
