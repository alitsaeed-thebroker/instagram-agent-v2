from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd().resolve()

if __name__ == "__main__":
    required = [
        ROOT / "src" / "department3" / "phase4f_certification.py",
        ROOT / "src" / "department3" / "real_estate_brain.py",
        ROOT / "src" / "department3" / "real_estate_orchestrator.py",
        ROOT / "src" / "department3" / "live_orchestration.py",
        ROOT / "src" / "department3" / "runtime_guard.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"FAIL: missing {path}")
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    text = (ROOT / "src" / "department3" / "phase4f_certification.py").read_text(encoding="utf-8")
    forbidden = ("requests.", "httpx.", "graph.facebook.com", "publish_to_instagram", "MetaPublisher")
    if any(x in text for x in forbidden):
        raise SystemExit("FAIL: certification runner contains an external publishing/network marker")

    print("Phase 4F static verification: PASS")
    print("- Certification runner installed")
    print("- Phase 4E brain installed")
    print("- Canonical live orchestration installed")
    print("- Runtime authority guard installed")
    print("- No publishing/network marker in certification runner")
